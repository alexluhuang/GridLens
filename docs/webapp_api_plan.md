# GridLens Web App Plan

This repository now includes a first-pass API backend that reuses the existing local GridLens execution and analysis
layers. The intended split is:

```text
Browser frontend (local dev or deployed web app)
  -> GridLens API on EC2
  -> local project storage on EC2
  -> Dockerized GridPACK execution
  -> parsed GridPACK outputs
  -> interactive analysis JSON for browser charts
```

## What The API Reuses

- `gridlens.core.project` for project storage and run directories
- `gridlens.runner.gridpack_runner` for Docker/GridPACK execution
- `gridlens.analysis.interactive` for lightweight chart-oriented analysis payloads

This avoids maintaining a second execution path just for the web app.

## Current API Flow

1. `POST /api/projects` uploads the user input files, including `input.xml` and the network file.
2. `POST /api/projects/{project_id}/runs` creates a run folder and starts GridPACK in a background worker thread.
3. The frontend polls `GET /api/projects/{project_id}/runs/{run_id}` and optionally `GET .../log`.
4. After the run completes, the frontend calls `POST /api/projects/{project_id}/runs/{run_id}/analysis/interactive`.
5. The API returns JSON row sets such as `line_rows`, `control_area_rows`, and `voltage_group_rows` for interactive
   browser plots.

## Local Frontend + AWS API

For local web-app development against the EC2 backend:

```bash
export GRIDLENS_API_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:5173
export GRIDLENS_API_HOST=0.0.0.0
export GRIDLENS_API_PORT=8000
gridlens-api
```

Then point the frontend to the EC2 API base URL with an environment variable such as:

```bash
VITE_GRIDLENS_API_BASE_URL=http://<ec2-public-host>:8000
```

## Recommended Next Step For Production

This API is a strong bridge from the desktop app to a web app, but for an EC2 deployment serving up to roughly 3000
users, the next step should be a job queue plus object storage rather than running all long jobs directly inside the web
process.

Recommended production pieces:

- `FastAPI` app behind `nginx` or an AWS load balancer
- background worker queue such as Celery, RQ, or AWS SQS + worker processes
- shared storage for outputs, preferably S3 for finished artifacts
- Postgres for project/run metadata instead of only scanning local folders
- authentication and per-user authorization before accepting uploads

## Frontend Plotting

The existing desktop interactive analysis is already broken into compact row sets. Those can map cleanly to web charting
libraries such as Plotly, ECharts, or Recharts while preserving interactivity.

Example frontend uses:

- `line_rows`: scatter, sortable table, drill-down list
- `control_area_rows`: bar chart
- `voltage_group_rows`: grouped bar chart

## Included Frontend Scaffold

This repository now includes a Vite + React browser client under `webapp/`.

It currently supports:

- creating a project by uploading the XML and network files
- starting a GridPACK run
- polling run status and reading the run log
- rendering interactive Plotly charts from the interactive analysis endpoint

For exact local testing steps, see `webapp/README.md`.
