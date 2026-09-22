# GridLens

GridLens is a local Python desktop application for running GridPACK contingency analysis through a prebuilt
Docker container. You set up a project, run a case, and read the results as tables and graphs without leaving
your machine.

The app also has an optional Agent tab that answers questions about completed runs in plain language. It
drives an AI command-line tool that you install yourself, and it only uses a model served on a loopback
address. GridLens ships no model and no credentials.

The intended deployment target is NVIDIA DGX Spark on DGX OS 7, which is Ubuntu 24.04 on ARM64. On other
architectures, the app detects the host and passes the matching Docker platform flag.

This app is local-only by design. Pull the GridPACK Docker image before you open sensitive files in the app.

## Quick start for development

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

To check your local environment:

```bash
python3 scripts/check_environment.py
```

## Manual Docker equivalent

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

On x86_64 systems the platform is `linux/amd64`. On DGX Spark ARM64 it is usually `linux/arm64`.

## Repository layout

```text
src/gridlens/
  gui/        PySide6 tabs and main window
  core/       settings, projects, validation, run manifests
  runner/     Docker probing, command construction, GridPACK execution
  analysis/   local output parsing, graph data, metrics, exports
  agent/      runtime adapters, session scoping, deterministic tools, MCP server
  resources/  application icon

tests/        core unit tests
docs/         architecture, install, user, security, packaging notes
docs/plans/   design notes and work in progress
packaging/    PyInstaller, Debian, and agent sandbox image files
scripts/      local helper scripts
samples/      small parser sample files
```

## Documentation

- [Architecture](docs/architecture.md)
- [Developer guide](docs/developer_guide.md)
- [DGX OS 7 install guide](docs/install_dgx_os7.md)
- [User guide](docs/user_guide.md)
- [CEII security notes](docs/security_ceii.md)
- [Packaging and distribution](docs/packaging_distribution.md)
- [Troubleshooting](docs/troubleshooting.md)

## Contributing and support

Read [Contributing](CONTRIBUTING.md) before you open a pull request. It covers the local-only rules that every
change has to keep.

Report bugs and ask questions at [GridLens issues](https://github.com/alexluhuang/GridLens/issues).

## License

GridLens is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).
