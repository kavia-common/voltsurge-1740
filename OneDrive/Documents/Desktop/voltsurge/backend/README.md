# VoltSurge Backend (FastAPI)

FastAPI backend for VoltSurge. Responsibilities:

- Accept CSV uploads
- Clean/normalize data (units -> kWh)
- Compute baseline (average kWh) and detect anomalies (> 20% above baseline)
- Store everything in-memory per session (no DB, no auth)
- Expose REST endpoints consumed by the static frontend in `frontend/`

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # (Windows: .\.venv\Scripts\Activate.ps1)
python -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open:

- Health: http://localhost:8000/health
- Swagger UI: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- Usage notes: http://localhost:8000/docs/usage

## Endpoints (expected by frontend)

- `GET /health`
- `POST /upload?timestamp_col=...&energy_col=...&unit_col=...` (multipart form field: `file`)
- `GET /sessions/{session_id}/summary`
- `GET /sessions/{session_id}/data?limit=...&offset=...`
- `GET /sessions/{session_id}/anomalies`
- `DELETE /sessions/{session_id}`
- `GET /sessions` (optional debugging)
- `DELETE /sessions` (clear all; optional debugging)

## CSV expectations

CSV must include the columns you specify in query params:

- `timestamp_col`: timestamp string (ISO recommended; backend stores as string but will attempt sorting by parsed datetime)
- `energy_col`: numeric
- `unit_col`: unit string (supported: kWh / Wh / MWh; common variations accepted)

Cleaning rules:

- Drop rows with missing/unparseable timestamp
- Drop rows with missing/unparseable energy
- Drop rows with missing/unsupported unit
- Drop exact duplicates (same timestamp, energy_kwh)
- Sort by timestamp

Anomaly definition:

- baseline is the mean of all cleaned `energy_kwh`
- anomaly if `energy_kwh > 1.2 * baseline_avg_kwh`
