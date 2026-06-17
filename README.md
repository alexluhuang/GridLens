# GridPACK Workbench

GridPACK Workbench is a local Python desktop application for running GridPACK contingency analysis through a prebuilt Docker container. It is designed for users who should not need to type terminal commands: they create a project, add input files, choose run settings, click Run, then review outputs and generate local reports.

The intended deployment target is NVIDIA DGX Spark / DGX OS 7, which is Ubuntu 24.04 based and may be either x86_64 or ARM64 depending on hardware. The app detects the host architecture and passes the matching Docker platform flag.

## Recommended Product Architecture

Use this stack for the first production-quality MVP:

- Python for application logic.
- PySide6 / Qt for Python for the GUI.
- Docker Engine for running the existing GridPACK image.
- Local project folders for CEII input files, run logs, manifests, outputs, reports, branch master datasets, and utilization plots.
- PyInstaller for the first pilot build.
- A Debian package for DGX OS 7 distribution.

Do not start with Flatpak. Flatpak is useful for sandboxed Linux apps, but this product needs deliberate access to Docker, local project folders, CEII files, and possibly NVIDIA container runtime integration. A `.deb` installer is the cleaner first target for DGX OS 7.

## Why PySide6

PySide6 is the best first GUI choice here because it gives Python access to Qt, a mature desktop application framework with good Linux support and professional widgets. PyQt is also capable, but its GPL/commercial licensing is less convenient for a product unless you plan that license path. PySimpleGUI is easier for small prototypes, but this app needs a durable multi-tab workflow, file management, long-running background jobs, logs, result tables, report previews, and packaging.

## CEII Defaults

This app is local-only by design:

- No cloud upload.
- No telemetry.
- No crash reporting.
- Docker runs default to `--network none`.
- Docker runs default to `--pull=never`.
- Only the per-run `work/` folder is mounted into the container.
- Each run writes `manifest.json`, `status.json`, and `logs/run.log`.
- Input files are copied into the project so runs are auditable and reproducible.

Pull the GridPACK Docker image before opening sensitive files in the app.

## Quick Start For Development

```bash
cd /home/alh360/Documents/gridpack-workbench-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
gridpack-workbench
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
  -v /path/to/project/runs/2026-06-12_15-30-22/work:/app/workspace \
  -w /app/workspace \
  pnnl/gridpack:latest \
  mpirun -n 4 ca.x input.xml
```

On x86_64 systems the platform is `linux/amd64`; on DGX Spark ARM64 it is typically `linux/arm64`.

## Repository Layout

```text
src/gridpack_workbench/
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
