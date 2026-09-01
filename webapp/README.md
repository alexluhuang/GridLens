# GridLens Web Client

This frontend talks to the GridLens API and lets you:

- upload project input files such as `.raw`, `.csv`, `.con`, `.mon`, and existing `.xml`
- generate or update the GridPACK XML configuration in the browser
- start GridPACK runs
- poll run status and logs
- download individual run output files
- export full runs as ZIP archives
- build interactive browser charts from the GridLens interactive analysis endpoint

It can now also run as a static GitHub Pages frontend backed by:

- an EC2-hosted GridLens API
- Amazon Cognito for email-and-password sign-in
- per-user project isolation enforced by the API

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

If you want to test the Cognito login flow locally, also set:

```bash
VITE_GRIDLENS_AUTH_MODE=cognito
VITE_GRIDLENS_COGNITO_DOMAIN=https://<your-cognito-domain>.auth.<region>.amazoncognito.com
VITE_GRIDLENS_COGNITO_CLIENT_ID=<your-cognito-app-client-id>
```

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
VITE_GRIDLENS_AUTH_MODE=cognito
VITE_GRIDLENS_COGNITO_DOMAIN=https://<your-cognito-domain>.auth.<region>.amazoncognito.com
VITE_GRIDLENS_COGNITO_CLIENT_ID=<your-cognito-app-client-id>
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

## GitHub Pages Deployment

The repository now includes [`.github/workflows/github-pages.yml`](/Users/hannah/Documents/GridLens/.github/workflows/github-pages.yml), which builds and deploys the frontend to GitHub Pages.

Set these GitHub repository variables before enabling the workflow:

- `VITE_GRIDLENS_API_BASE_URL`
  Example: `http://3.18.103.82:8000`
- `VITE_GRIDLENS_AUTH_MODE`
  Use `cognito` for the protected multi-user deployment
- `VITE_GRIDLENS_COGNITO_DOMAIN`
  Example: `https://your-domain.auth.us-east-2.amazoncognito.com`
- `VITE_GRIDLENS_COGNITO_CLIENT_ID`
  Your Cognito app client ID
- `VITE_PUBLIC_BASE_PATH`
  Use `/` for a custom domain or `/<repo-name>/` for repo-scoped GitHub Pages

After that:

1. Enable GitHub Pages in the repository settings and choose `GitHub Actions` as the source.
2. Push to `main`, or manually trigger the workflow.
3. Add the resulting GitHub Pages URL to:
   `GRIDLENS_API_CORS_ORIGINS` on EC2
4. Add the same GitHub Pages URL as an allowed callback URL and logout URL in Cognito.

## Publish On An EC2 Host

The simplest hosted setup is:

- `uvicorn` / `gridlens-api` on the EC2 instance
- `nginx` serving `webapp/dist`
- `nginx` reverse-proxying `/api` to `127.0.0.1:8000`

See [docs/web_deployment.md](../docs/web_deployment.md) for the full deployment checklist.

## Suggested Frontend Next Steps

- add token refresh support so very long sessions do not require a fresh sign-in
- add pagination or filtering for large run histories
- add richer drill-down views for line metadata and contingency details
