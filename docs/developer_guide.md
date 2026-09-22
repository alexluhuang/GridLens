# Developer guide

## Setup

```bash
cd /path/to/gridpack-workbench-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev,analysis]"
```

`requirements.txt` lists the minimal GUI dependency. `requirements-analysis.txt` lists the optional plotting
and data dependencies.

## Run the app

```bash
source .venv/bin/activate
gridlens
```

Or:

```bash
scripts/run_app.sh
```

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
