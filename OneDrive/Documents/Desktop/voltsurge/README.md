# VoltSurge (Full Stack) — FastAPI + Static HTML/JS

VoltSurge is a simple local-first full stack demo:

- **Backend**: FastAPI (`backend/`)  
  - CSV upload → cleaning → unit normalization to **kWh**
  - Baseline average computation
  - Anomaly detection: **energy_kwh > 1.2 × baseline_avg_kwh**
  - Stores results **in-memory per session** (no DB, no auth)
- **Frontend**: Static HTML/CSS/JS SPA (`frontend/`)  
  - Upload CSV, map columns, view dashboard (Chart.js via CDN)

## Prerequisites

- Python **3.10+** (3.11 recommended)
- A modern browser
- Optional: `curl` (for smoke tests)

No database and no Node.js build step.

---

## Run locally (recommended)

### 1) Start the backend (port 8000)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend URLs:

- Health: http://localhost:8000/health
- Swagger UI: http://localhost:8000/docs
- Usage notes: http://localhost:8000/docs/usage

**CORS:** The backend enables permissive CORS for local development so the frontend can run on a different port (e.g., `5173`).

### 2) Serve the frontend (port 5173)

Serving via HTTP is recommended (opening `file://.../index.html` can break `fetch()` in many browsers):

```bash
cd frontend
python -m http.server 5173
```

Open:

- http://localhost:5173

In the UI, the API Base URL defaults to `http://localhost:8000`.

---

## API contracts (what the frontend calls)

- `GET /health`
- `POST /upload?timestamp_col=...&energy_col=...&unit_col=...` (multipart form field: `file`)
- `GET /sessions/{session_id}/summary`
- `GET /sessions/{session_id}/data?limit=...&offset=...`
- `GET /sessions/{session_id}/anomalies`
- `DELETE /sessions/{session_id}`

---

## Quick smoke tests (backend)

### A) Health check

```bash
curl -sS http://localhost:8000/health
```

Expected: `{"status":"ok","time":"...Z"}`

### B) Create a tiny CSV and upload

```bash
cat > /tmp/voltsurge_smoke.csv <<'CSV'
timestamp,energy,unit
2026-01-01T00:00:00Z,10,kWh
2026-01-01T01:00:00Z,12,kWh
2026-01-01T02:00:00Z,30,kWh
CSV
```

```bash
curl -sS \
  -X POST "http://localhost:8000/upload?timestamp_col=timestamp&energy_col=energy&unit_col=unit" \
  -F "file=@/tmp/voltsurge_smoke.csv"
```

Expected: JSON includes `session_id`, `rows_received`, `rows_cleaned`, `baseline_avg_kwh`, `anomalies_count`.

### C) Fetch session data

Replace `$SESSION_ID` with the value returned above:

```bash
curl -sS "http://localhost:8000/sessions/$SESSION_ID/summary"
curl -sS "http://localhost:8000/sessions/$SESSION_ID/data?limit=100000&offset=0"
curl -sS "http://localhost:8000/sessions/$SESSION_ID/anomalies"
```

### D) Cleanup

```bash
curl -sS -X DELETE "http://localhost:8000/sessions/$SESSION_ID"
```

---

## Frontend smoke test

1. Start backend at `http://localhost:8000`
2. Start frontend at `http://localhost:5173`
3. Click **Test connection**
4. Upload `/tmp/voltsurge_smoke.csv`, map:
   - timestamp → `timestamp`
   - energy → `energy`
   - unit → `unit`
5. Click **Upload & Process**

Expected:
- Session summary populates
- Chart renders
- Anomaly list shows the `30 kWh` point (since it is > 1.2× baseline)

---

## Notes

- Sessions are **in-memory only** and are lost when the backend restarts.
- Chart.js is loaded via CDN, so the frontend needs internet access to render charts.
