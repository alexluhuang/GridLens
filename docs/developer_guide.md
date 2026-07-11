# Developer Guide

## Setup

```bash
cd /path/to/gridpack-workbench-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev,analysis]"
```


The minimal GUI dependency is also listed in `requirements.txt`; optional plotting/data dependencies are listed in
`requirements-analysis.txt`.

## Run The App

```bash
source .venv/bin/activate
gridlens
```

or:

```bash
scripts/run_app.sh
```

## Run Tests

The primary test runner is `pytest`:

```bash
python -m pytest
```

Use the editable install from the setup section before running the full suite so GUI and optional analysis dependencies
are available. Individual tests are intentionally small and independent; prefer adding a focused regression test before
changing parser, analysis, runner, or GUI behavior.

The test suite also checks package metadata, console-script wiring, runtime dependency mirrors, and local README
documentation links. Keep `pyproject.toml`, `requirements.txt`, `README.md`, and `src/gridlens/__init__.py`
in sync when changing packaging or release information.

For headless machines, Qt tests set `QT_QPA_PLATFORM=offscreen` in the test module.

## Development Order

Build the product in this order:

1. Confirm one known GridPACK case runs manually with Docker.
2. Confirm `docker_command.py` builds the correct command.
3. Confirm `gridpack_runner.py` runs that case through Python.
4. Confirm project folders, manifests, status files, and logs are correct.
5. Use the GUI to run the same case.
6. Add exact output parsers.
7. Add graph data, analysis manifests, and exports.
8. Package with PyInstaller.
9. Wrap PyInstaller output in a `.deb`.
10. Test on a clean DGX OS 7 account.

## Code Style

Keep user-sensitive behavior in `core/` and `runner/`, not in GUI event handlers. The GUI should gather values and call
well-tested functions.

Never build Docker commands as shell strings. Build a list of arguments and run it without `shell=True`.

Keep modules organized around one responsibility. For example, parsed GridPACK data flows through `analysis/parsers.py`,
`analysis/enrichment.py`, `analysis/metrics.py`, and `analysis/dataset.py` before graph data or exports are written.
Add small helper modules when they make behavior reusable and testable.

Use explicit, readable Python over clever shortcuts. Public functions and non-obvious helpers should have concise
docstrings that explain behavior rather than repeat the function signature.
