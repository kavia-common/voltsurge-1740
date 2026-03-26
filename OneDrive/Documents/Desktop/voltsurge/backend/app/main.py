from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.processing import process_csv_bytes
from app.services.sessions import (
    SessionNotFoundError,
    clear_all_sessions,
    create_session,
    delete_session,
    get_session,
    list_sessions_preview,
)

openapi_tags = [
    {"name": "Health", "description": "Service health checks."},
    {"name": "Upload", "description": "CSV upload and processing."},
    {"name": "Sessions", "description": "Retrieve processed results from in-memory sessions."},
    {"name": "Docs", "description": "Additional documentation endpoints."},
]


class HealthResponse(BaseModel):
    status: str = Field(..., description="Health status string.")
    time: str = Field(..., description="UTC ISO timestamp of the response.")


class SessionSummaryResponse(BaseModel):
    session_id: str = Field(..., description="In-memory session identifier.")
    created_at: str = Field(..., description="UTC ISO time when the session was created.")
    rows_received: int = Field(..., description="Number of CSV rows read (excluding header when present).")
    rows_cleaned: int = Field(..., description="Number of valid rows kept after cleaning.")
    baseline_avg_kwh: float = Field(..., description="Baseline average energy usage in kWh across cleaned rows.")
    anomalies_count: int = Field(..., description="Count of anomalies detected (> 1.2x baseline).")
    total_energy_kwh: float = Field(..., description="Total energy (sum) in kWh across cleaned rows.")
    min_energy_kwh: float = Field(..., description="Minimum cleaned energy value in kWh.")
    max_energy_kwh: float = Field(..., description="Maximum cleaned energy value in kWh.")


class DataPoint(BaseModel):
    timestamp: str = Field(..., description="Timestamp for the datapoint (as string).")
    energy_kwh: float = Field(..., description="Energy value normalized to kWh.")
    is_anomaly: Optional[bool] = Field(
        default=None, description="Whether this datapoint is an anomaly (optional convenience flag)."
    )


class Anomaly(BaseModel):
    timestamp: str = Field(..., description="Timestamp of the anomalous datapoint.")
    energy_kwh: float = Field(..., description="Energy value in kWh at the timestamp.")
    baseline_avg_kwh: float = Field(..., description="Baseline average kWh for the session.")
    threshold_kwh: float = Field(..., description="Anomaly threshold (1.2x baseline).")
    ratio: float = Field(..., description="energy_kwh / baseline_avg_kwh")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


app = FastAPI(
    title="VoltSurge Backend API",
    description=(
        "FastAPI backend for VoltSurge: upload energy CSVs, normalize units to kWh, compute baseline, "
        "detect anomalies (>20% above baseline), and serve results from an in-memory session store."
    ),
    version="1.0.0",
    openapi_tags=openapi_tags,
)

# Permissive CORS for local development (static frontend served from another port).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
    description="Returns a simple health response to confirm the backend is reachable.",
    operation_id="health_check",
)
# PUBLIC_INTERFACE
def health() -> HealthResponse:
    """Health check endpoint.

    Returns:
        HealthResponse: status and current UTC time.
    """
    return HealthResponse(status="ok", time=_utc_now_iso())


@app.get(
    "/docs/usage",
    tags=["Docs"],
    summary="Usage notes",
    description="Human-readable usage notes for local development and API calling patterns.",
    operation_id="docs_usage",
)
# PUBLIC_INTERFACE
def docs_usage() -> JSONResponse:
    """Return brief usage notes for the API.

    Returns:
        JSONResponse: Helpful notes for calling the API from the frontend.
    """
    body = {
        "upload": {
            "endpoint": "POST /upload?timestamp_col=...&energy_col=...&unit_col=...",
            "multipart_field": "file",
            "notes": [
                "Filename must end with .csv",
                "Provide correct column names via query params (as in frontend mapping).",
            ],
        },
        "session_endpoints": [
            "GET /sessions/{id}/summary",
            "GET /sessions/{id}/data?limit=...&offset=...",
            "GET /sessions/{id}/anomalies",
            "DELETE /sessions/{id}",
        ],
        "anomaly_definition": "energy_kwh > 1.2 * baseline_avg_kwh",
        "storage": "In-memory only; sessions disappear when the backend restarts.",
    }
    return JSONResponse(content=body)


@app.post(
    "/upload",
    response_model=SessionSummaryResponse,
    tags=["Upload"],
    summary="Upload CSV and create a processing session",
    description=(
        "Upload a CSV file, clean it, normalize energy units to kWh, compute baseline average kWh, "
        "detect anomalies (>20% above baseline), and store results in an in-memory session."
    ),
    operation_id="upload_csv",
)
# PUBLIC_INTERFACE
async def upload(
    timestamp_col: str = Query(..., description="Name of the timestamp column in the CSV."),
    energy_col: str = Query(..., description="Name of the energy usage column in the CSV."),
    unit_col: str = Query(..., description="Name of the unit column in the CSV (kWh/Wh/MWh variants)."),
    file: UploadFile = File(..., description="CSV file to upload."),
) -> SessionSummaryResponse:
    """Upload and process a CSV file.

    Args:
        timestamp_col: CSV column name containing timestamps.
        energy_col: CSV column name containing energy values.
        unit_col: CSV column name containing units.
        file: Multipart file upload (must be a .csv filename).

    Returns:
        SessionSummaryResponse: Summary stats for the created session.

    Raises:
        HTTPException: If file is not CSV, parsing/cleaning fails, or no valid rows remain.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv uploads are supported.")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty upload.")

    try:
        result = process_csv_bytes(
            raw_bytes=raw_bytes,
            timestamp_col=timestamp_col,
            energy_col=energy_col,
            unit_col=unit_col,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    session = create_session(result)
    return SessionSummaryResponse(**session.summary_dict())


@app.get(
    "/sessions",
    tags=["Sessions"],
    summary="List sessions (debugging)",
    description="Returns a small preview of in-memory sessions (count + a few IDs).",
    operation_id="list_sessions",
)
# PUBLIC_INTERFACE
def sessions_list() -> JSONResponse:
    """List session IDs preview.

    Returns:
        JSONResponse: sessions_count and session_ids_preview.
    """
    preview = list_sessions_preview()
    return JSONResponse(content=preview)


@app.delete(
    "/sessions",
    tags=["Sessions"],
    summary="Clear all sessions (debugging)",
    description="Deletes all in-memory sessions.",
    operation_id="clear_all_sessions",
)
# PUBLIC_INTERFACE
def sessions_clear_all() -> JSONResponse:
    """Clear all sessions.

    Returns:
        JSONResponse: status information.
    """
    cleared = clear_all_sessions()
    return JSONResponse(content={"deleted_sessions": cleared})


@app.get(
    "/sessions/{session_id}/summary",
    response_model=SessionSummaryResponse,
    tags=["Sessions"],
    summary="Get session summary",
    description="Returns baseline and summary statistics for a given session.",
    operation_id="get_session_summary",
)
# PUBLIC_INTERFACE
def get_summary(session_id: str) -> SessionSummaryResponse:
    """Get session summary.

    Args:
        session_id: Session identifier.

    Returns:
        SessionSummaryResponse: Summary of processed session data.

    Raises:
        HTTPException: If session does not exist.
    """
    try:
        session = get_session(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SessionSummaryResponse(**session.summary_dict())


@app.get(
    "/sessions/{session_id}/data",
    response_model=List[DataPoint],
    tags=["Sessions"],
    summary="Get normalized datapoints (kWh)",
    description="Returns cleaned, normalized time-series datapoints for the session. Supports limit/offset paging.",
    operation_id="get_session_data",
)
# PUBLIC_INTERFACE
def get_data(
    session_id: str,
    limit: int = Query(100000, ge=1, le=200000, description="Max number of rows to return."),
    offset: int = Query(0, ge=0, description="Number of rows to skip before returning results."),
) -> List[DataPoint]:
    """Get normalized datapoints for a session.

    Args:
        session_id: Session identifier.
        limit: Maximum number of rows to return.
        offset: Starting offset.

    Returns:
        List[DataPoint]: List of timestamp/energy_kwh datapoints.

    Raises:
        HTTPException: If session does not exist.
    """
    try:
        session = get_session(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    items = session.data_points[offset : offset + limit]
    return [DataPoint(**dp) for dp in items]


@app.get(
    "/sessions/{session_id}/anomalies",
    response_model=List[Anomaly],
    tags=["Sessions"],
    summary="Get anomalies",
    description="Returns anomalies detected for the session (energy_kwh > 1.2 * baseline_avg_kwh).",
    operation_id="get_session_anomalies",
)
# PUBLIC_INTERFACE
def get_anomalies(session_id: str) -> List[Anomaly]:
    """Get anomalies for a session.

    Args:
        session_id: Session identifier.

    Returns:
        List[Anomaly]: List of anomaly objects.

    Raises:
        HTTPException: If session does not exist.
    """
    try:
        session = get_session(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return [Anomaly(**a) for a in session.anomalies]


@app.delete(
    "/sessions/{session_id}",
    tags=["Sessions"],
    summary="Delete a session",
    description="Deletes a single in-memory session and its processed data.",
    operation_id="delete_session",
)
# PUBLIC_INTERFACE
def delete_session_endpoint(session_id: str) -> JSONResponse:
    """Delete a session.

    Args:
        session_id: Session identifier.

    Returns:
        JSONResponse: status information.

    Raises:
        HTTPException: If session does not exist.
    """
    try:
        delete_session(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return JSONResponse(content={"deleted": True, "session_id": session_id})


# Friendly root response (optional).
@app.get(
    "/",
    tags=["Docs"],
    summary="Root",
    description="Simple root endpoint that points to docs.",
    operation_id="root",
)
# PUBLIC_INTERFACE
def root() -> JSONResponse:
    """Root endpoint.

    Returns:
        JSONResponse: Basic API info.
    """
    return JSONResponse(
        content={
            "name": "VoltSurge Backend API",
            "status": "ok",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }
    )
