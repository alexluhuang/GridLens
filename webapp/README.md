# GridLens Web Client

This frontend talks to the GridLens API and lets you:

- upload project input files such as `.raw`, `.csv`, `.con`, `.mon`, and existing `.xml`
- generate or update the GridPACK XML configuration in the browser
- start GridPACK runs
- poll run status and logs
- download individual run output files
- export full runs as ZIP archives
- build interactive browser charts from the GridLens interactive analysis endpoint

## Local Development Against A Local API

1. Start the GridLens API:

```bash
cd /Users/hannah/Documents/GridLens
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[web]"
export GRIDLENS_API_HOST=127.0.0.1
export GRIDLENS_API_PORT=8000
export GRIDLENS_API_CORS_ORIGINS=http://localhost:5173
gridlens-api
```

2. In a second terminal, start the frontend:

```bash
cd /Users/hannah/Documents/GridLens/webapp
npm install
npm run dev
```

3. Open `http://localhost:5173`.

Because the Vite dev server proxies `/api` to `http://localhost:8000`, you do not need a frontend env var in this mode.

## Local Development Against The EC2 API

1. Run the API on the EC2 instance with CORS enabled for local dev:

```bash
export GRIDLENS_API_CORS_ORIGINS=http://localhost:5173
export GRIDLENS_API_HOST=0.0.0.0
export GRIDLENS_API_PORT=8000
export GRIDLENS_API_PROJECTS_ROOT=/home/ubuntu/GridLensWebProjects
gridlens-api
```

2. In the frontend directory, copy `.env.local.example` to `.env.local` and update it:

```bash
VITE_GRIDLENS_API_BASE_URL=http://<your-ec2-host-or-ip>:8000
```

3. Start the frontend:

```bash
cd /Users/hannah/Documents/GridLens/webapp
npm install
npm run dev
```

4. Open `http://localhost:5173`.

## Production Build

Build the static frontend bundle with:

```bash
cd /Users/hannah/Documents/GridLens/webapp
npm install
npm run build
```

The published assets are written to `webapp/dist`.

## Publish On An EC2 Host

The simplest hosted setup is:

- `uvicorn` / `gridlens-api` on the EC2 instance
- `nginx` serving `webapp/dist`
- `nginx` reverse-proxying `/api` to `127.0.0.1:8000`

See [docs/web_deployment.md](../docs/web_deployment.md) for the full deployment checklist.

## Suggested Frontend Next Steps

- add authentication before exposing uploads publicly
- add pagination or filtering for large run histories
- add richer drill-down views for line metadata and contingency details
