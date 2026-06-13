# Developer Guide

## Setup

```bash
cd /home/alh360/Documents/gridpack-workbench-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev,analysis]"
```

If the machine has no network access, install dependencies from an internal wheelhouse or an offline package repository approved for CEII environments.

The minimal GUI dependency is also listed in `requirements.txt`; optional plotting/data dependencies are listed in `requirements-analysis.txt`.

## Run The App

```bash
source .venv/bin/activate
gridpack-workbench
```

or:

```bash
scripts/run_app.sh
```

## Run Tests

The tests use only the standard library and the project source tree:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

If `pytest` is installed:

```bash
pytest
```

## Development Order

Build the product in this order:

1. Confirm one known GridPACK case runs manually with Docker.
2. Confirm `docker_command.py` builds the correct command.
3. Confirm `gridpack_runner.py` runs that case through Python.
4. Confirm project folders, manifests, status files, and logs are correct.
5. Use the GUI to run the same case.
6. Add exact output parsers.
7. Add polished reports and exports.
8. Package with PyInstaller.
9. Wrap PyInstaller output in a `.deb`.
10. Test on a clean DGX OS 7 account.

## Code Style

Keep user-sensitive behavior in `core/` and `runner/`, not in GUI event handlers. The GUI should gather values and call well-tested functions.

Never build Docker commands as shell strings. Build a list of arguments and run it without `shell=True`.
