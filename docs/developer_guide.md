# Developer guide

## Setup

GridLens needs Python 3.11 or later.

```bash
cd /path/to/gridpack-workbench-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev,analysis]"
```

On Windows, in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev,analysis]"
```

The analysis extras share one CPU stack and differ in RAPIDS, which is installed on Linux only:

- `analysis`: the CPU stack and RAPIDS for CUDA 13, which needs NVIDIA driver 580 or later. On Windows it
  installs the CPU stack alone.
- `analysis-cu12`: the CPU stack and RAPIDS for CUDA 12, for older drivers.
- `analysis-cpu`: the CPU stack alone, as the CI uses.

RAPIDS is pinned to 26.6, and numpy, pandas, pyarrow, and Dask to the versions it installs, so every platform
runs the same analysis libraries. Upgrade them together.

`requirements.txt` lists the runtime dependencies, and `requirements-analysis.txt` mirrors the `analysis`
extra.

## Run the app

```bash
source .venv/bin/activate
gridlens
```

Or:

```bash
scripts/run_app.sh
```

On Windows, run `scripts\run_app.ps1`.

## Run tests

The test runner is `pytest`:

```bash
python -m pytest
```

Do the editable install from the setup section first, so the GUI and the optional analysis dependencies are
available. Tests are deliberately small and independent. Add a focused regression test before you change
parser, analysis, runner, agent, or GUI behavior.

The suite also checks package metadata, console-script wiring, runtime dependency mirrors, and the
documentation links in the README. Keep `pyproject.toml`, `requirements.txt`, `README.md`, and
`src/gridlens/__init__.py` in sync when you change packaging or release information.

On a headless machine, the Qt tests set `QT_QPA_PLATFORM=offscreen` in the test module.

The GitHub Actions workflow in `.github/workflows/tests.yml` runs the suite on Ubuntu x86_64, Ubuntu ARM64,
and Windows x64, with the CPU analysis stack, and builds the Windows bundle. Its runners have no NVIDIA GPU,
so check GPU analysis, the Docker sandbox (`GRIDLENS_TEST_SANDBOX_IMAGE`), and a frozen build's MCP server
(`GRIDLENS_TEST_MCP_EXECUTABLE`) on an NVIDIA machine.

## Development order

Build the product in this order:

1. Confirm one known GridPACK case runs manually with Docker.
2. Confirm `docker_command.py` builds the correct command.
3. Confirm `gridpack_runner.py` runs that case through Python.
4. Confirm project folders, manifests, status files, and logs are correct.
5. Use the GUI to run the same case.
6. Add exact output parsers.
7. Add graph data, analysis manifests, and exports.
8. Package with PyInstaller.
9. Wrap the PyInstaller output in a `.deb`.
10. Test on a clean DGX OS 7 account.

## Code style

Keep user-sensitive behavior in `core/` and `runner/` rather than in GUI event handlers. The GUI gathers
values and calls well-tested functions.

Never build a Docker command as a shell string. Build a list of arguments and run it without `shell=True`.

Reach the operating system through `gridlens/system/`: open private files with `files.open_private`, lock
with `files.FileLock`, replace files with `files.replace`, name folders with `paths`, and start and stop
children with `processes`. Linux and Windows differ in each of these, and the modules there are where the
difference is handled and tested. Pass `encoding="utf-8"` to any `subprocess` call that decodes text.

Follow PEP 8 in new and changed code.

Keep each module organized around one responsibility. Parsed GridPACK data, for example, flows through
`analysis/parsers.py`, `analysis/enrichment.py`, `analysis/metrics.py`, and `analysis/dataset.py` before
anything writes graph data or exports. Add a small helper module when it makes behavior reusable and testable.

In `agent/`, keep provider-specific code inside its adapter. The registry in `agent/providers.py` is the only
place that maps a provider id to an adapter, and the tool service, session store, controller, and GUI are all
written against the contract in `agent/runtime.py`.

Use explicit, readable Python over clever shortcuts. Give public functions and non-obvious helpers short
docstrings that explain behavior instead of repeating the signature.

## Design notes

`docs/plans/` holds working documents rather than reference material:

- `ai_planning_agent.md` is the implementation plan for the Agent tab.
- `agent_findings.md` is the verified defect register for that feature.
- `handoff.md` records what is built, what was measured, and what is still open.
