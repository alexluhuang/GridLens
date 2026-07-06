# GridLens

GridLens is a local Python desktop application for running GridPACK contingency analysis through a prebuilt Docker container. 

The intended deployment target is NVIDIA DGX Spark / DGX OS 7, which is Ubuntu 24.04 based on ARM64. For other architectures, the app detects the host architecture and passes the matching Docker platform flag.

This app is local-only by design. Pull the GridPACK Docker image before opening sensitive files in the app.

## Quick Start For Development

```bash
cd /home/alh360/Documents/gridlens-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
gridlens
```

If you only want to verify the core code without installing GUI dependencies:

```bash
PYTHONPATH=src python3 -m pytest
python3 scripts/check_environment.py
```

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
  analysis/   local output parsing, reports, charts, exports
  resources/  default settings and icon

tests/        core unit tests
docs/         architecture, install, user, security, packaging notes
packaging/    PyInstaller and Debian package files
scripts/      local helper scripts
samples/      small parser/reporting sample files
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
