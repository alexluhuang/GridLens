# Contributing To GridLens

GridLens is intended to become an open-source desktop application for local GridPACK contingency analysis.
Contributions should keep the app understandable for regulators and maintainable for future developers.

## Local-Only And CEII Rules

- Do not add cloud uploads, telemetry, remote crash reporting, or external logging.
- Do not send project inputs, GridPACK outputs, run manifests, or derived exports to online services.
- Keep Docker runs local and least-privilege by default: `--network none`, `--pull=never`, and only the per-run
  `work/` directory mounted into the container.
- Do not commit real CEII data, proprietary cases, local run folders, generated exports, or screenshots containing
  sensitive grid information.
- Use small synthetic fixtures in `tests/` and `samples/`.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev,analysis]"
```

Run the app with:

```bash
gridlens
```

## Verification

Run the full suite before submitting changes:

```bash
python -m pytest
python -m compileall -q src tests
git diff --check
```

The test suite is intentionally focused. Add or update a test when changing parsing, analysis, Docker command
construction, project-folder behavior, GUI view-model logic, package metadata, or documentation links.

## Code Organization

- `core/` owns settings, projects, validation, and manifests.
- `runner/` owns Docker probing, command construction, and process execution.
- `analysis/` owns parsing, enrichment, metrics, master exports, plots, and reports.
- `gui/` owns PySide6 widgets and view-specific adapters. Keep business rules in pure helper modules when possible.

Prefer small functions with clear names. Add a new helper module when it makes behavior reusable and testable. Avoid
large GUI event handlers that also validate data, build Docker requests, parse outputs, or write reports.

## Style Expectations

- Build Docker commands as argument lists. Never use `shell=True`.
- Validate user-provided paths, project names, Docker image names, executables, and MPI process counts before creating
  run artifacts.
- Prefer explicit, readable Python over clever shortcuts.
- Keep public functions and non-obvious helpers documented with concise docstrings.
- Keep generated files, virtual environments, caches, and local project folders out of Git.

## Pull Request Checklist

- The app remains local-only and CEII-safe by default.
- New behavior has a focused test or a clear reason it cannot be tested automatically.
- `python -m pytest` passes.
- `python -m compileall -q src tests` passes.
- `git diff --check` reports no whitespace errors.
- README or docs are updated when workflow, packaging, security, or user-visible behavior changes.
