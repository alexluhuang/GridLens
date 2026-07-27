# GridLens Web Client

This frontend talks to the GridLens API and lets you:

- upload `input.xml` plus the network file
- start GridPACK runs
- poll run status and logs
- build interactive browser charts from the GridLens interactive analysis endpoint

## Local Development Against A Local API

1. Start the GridLens API:

```bash
cd /Users/hannah/Documents/GridLens
python -m pip install -e ".[web]"
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

## Suggested Frontend Next Steps

- add authentication before exposing uploads publicly
- add pagination or filtering for large run histories
- add richer drill-down views for line metadata and contingency details
