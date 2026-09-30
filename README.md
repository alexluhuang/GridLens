# GridLens

GridLens is a local Python desktop application for running GridPACK contingency analysis through a prebuilt
Docker container. You set up a project, run a case, and read the results as tables and graphs without leaving
your machine.

The Sensitivity Analysis tab runs what-if studies: it adds, removes, or changes loads, generators, and
branches in a copy of a PSS/E RAW case of version 33, 34, or 35, and runs GridPACK N-1 analysis on the copy.
It rewrites only the lines you edit, and the project's case stays as it is.

The app also has an optional Agent tab: Clarke, a planning agent that answers questions about any project
file in plain language, and can set up projects, configure and start runs, and build analyses for you. It
runs Hermes Agent against a model served by Ollama on this machine, and never sends project data online.
GridLens ships no model and no credentials; the first time you open the tab, it offers to install Hermes,
Ollama, and a model for you. See [Clarke, the planning agent](docs/clarke.md).

GridLens runs GridPACK in Docker, and uses an NVIDIA GPU for its analysis and for Clarke's local model. It
runs on:

| Platform | Install | Analysis |
|---|---|---|
| NVIDIA DGX Spark on DGX OS 7 (Ubuntu 24.04, ARM64) | The `.deb` package | RAPIDS on the GPU |
| Other ARM64 or x86_64 Linux with an NVIDIA GPU | The `.deb` package on Ubuntu 24.04 or later, or from source | RAPIDS on the GPU |
| Windows 10 or 11 x64, native | The Windows installer | CPU Dask |
| Windows 11 x64, WSL2 | The `.deb` package in Ubuntu 24.04 | RAPIDS on the GPU |

The app detects the host's architecture and passes the matching Docker platform flag. See the
[DGX OS 7 install guide](docs/install_dgx_os7.md), which also covers other Linux machines, and the
[Windows install guide](docs/install_windows.md).

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

On Windows, in PowerShell, create the environment with `python -m venv .venv` and activate it with
`.venv\Scripts\Activate.ps1`. The `analysis` extra adds the analysis libraries, with RAPIDS on Linux; see the
[developer guide](docs/developer_guide.md).

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
  --mount type=bind,source=/path/to/project/runs/YYYY-MM-DD_HH-MM-SS/work,target=/app/workspace \
  -w /app/workspace \
  pnnl/gridpack:latest \
  mpirun -n 4 ca.x input.xml
```

On x86_64 systems the platform is `linux/amd64`. On DGX Spark ARM64 it is usually `linux/arm64`. Windows
has no user IDs to pass, so there the command has no `-u` or `HOME` setting.

## Repository layout

```text
src/gridlens/
  gui/        PySide6 tabs and main window
  core/       settings, projects, validation, run manifests, sensitivity runs
  psse/       PSS/E RAW record layouts and the surgical RAW patcher
  runner/     Docker probing, command construction, GridPACK execution
  analysis/   local output parsing, graph data, metrics, exports
  agent/      runtime adapters, sessions, deterministic tools, background jobs, MCP server
  system/     private files, locks, folders, and child processes on Linux and Windows
  resources/  application icon

tests/        core unit tests
tests/data/   synthetic three-bus RAW cases in versions 33, 34, and 35
docs/         architecture, install, user, security, packaging notes
docs/plans/   design notes and work in progress
packaging/    PyInstaller, Debian, Windows installer, and agent sandbox image files
scripts/      local helper scripts
samples/      small parser sample files
```

## Documentation

- [Architecture](docs/architecture.md)
- [Developer guide](docs/developer_guide.md)
- [DGX OS 7 install guide](docs/install_dgx_os7.md)
- [Windows install guide](docs/install_windows.md)
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
