# GridLens

GridLens is a local Python desktop application for running GridPACK contingency analysis through a prebuilt Docker container. 

The intended deployment target is NVIDIA DGX Spark / DGX OS 7, which is Ubuntu 24.04 based on ARM64. For other architectures, the app detects the host architecture and passes the matching Docker platform flag.

This app is local-only by design. Pull the GridPACK Docker image before opening sensitive files in the app.

## Quick Start For Development

```bash
cd /path/to/gridpack-workbench-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
gridlens
```

The full test suite expects the development dependencies, including PySide6:

```bash
python -m pytest
```

For a quick local environment smoke check:

```bash
python3 scripts/check_environment.py
```

## Web API Mode

GridLens now also includes a backend API layer for a browser-based frontend. Install the web dependencies and run:

```bash
python -m pip install -e ".[dev,web]"
gridlens-api
```

The API defaults to `http://0.0.0.0:8000` and stores uploaded web projects under `~/GridLensWebProjects`.

- `GET /health`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}`
- `POST /api/projects/{project_id}/runs`
- `GET /api/projects/{project_id}/runs/{run_id}`
- `GET /api/projects/{project_id}/runs/{run_id}/log`
- `POST /api/projects/{project_id}/runs/{run_id}/analysis/interactive`

Set `GRIDLENS_API_CORS_ORIGINS` to allow a local frontend such as Vite or Next.js to call an API hosted on AWS.
The browser client scaffold lives in [webapp/README.md](webapp/README.md).

## Manual Docker Equivalent

The GUI builds a Docker command equivalent to:

```bash
docker run --rm \
  --pull=never \
  --network none \
  --platform linux/arm64 \
  -u "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v /path/to/project/runs/YYYY-MM-DD_HH-MM-SS/work:/app/workspace \
  -w /app/workspace \
  pnnl/gridpack:latest \
  mpirun -n 4 ca.x input.xml
```

On x86_64 systems the platform is `linux/amd64`; on DGX Spark ARM64 it is typically `linux/arm64`.

## Repository Layout

```text
src/gridlens/
  gui/        PySide6 tabs and main window
  core/       settings, projects, validation, run manifests
  runner/     Docker probing, command construction, GridPACK execution
  analysis/   local output parsing, graph data, metrics, exports
  resources/  application icon

tests/        core unit tests
docs/         architecture, install, user, security, packaging notes
packaging/    PyInstaller and Debian package files
scripts/      local helper scripts
samples/      small parser sample files
```

## Documentation

- [Architecture](docs/architecture.md)
- [Developer Guide](docs/developer_guide.md)
- [DGX OS 7 Install Guide](docs/install_dgx_os7.md)
- [User Guide](docs/user_guide.md)
- [CEII Security Notes](docs/security_ceii.md)
- [Packaging And Distribution](docs/packaging_distribution.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing](CONTRIBUTING.md)
