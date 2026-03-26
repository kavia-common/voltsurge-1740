# VoltSurge Frontend (Static SPA)

This is a static HTML/CSS/JS single-page app that talks to the VoltSurge FastAPI backend.

## Run locally

1) Start the backend (expected at `http://localhost:8000`).

2) Serve this folder via a static server (recommended to avoid `file://` fetch limitations):

```bash
cd frontend
python -m http.server 5173
```

Then open:

- http://localhost:5173

## What it does

- CSV upload + header preview (client-side)
- Column mapping UI (timestamp, energy, unit)
- Upload call to backend:

  - `POST /upload?timestamp_col=...&energy_col=...&unit_col=...`

- Dashboard calls:

  - `GET /sessions/<id>/summary`
  - `GET /sessions/<id>/data?limit=100000&offset=0`
  - `GET /sessions/<id>/anomalies`

Charts are rendered with Chart.js (loaded via CDN).
