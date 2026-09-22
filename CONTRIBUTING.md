# Contributing To GridLens

GridLens is intended to become an open-source desktop application for local GridPACK contingency analysis.
Contributions should keep the app understandable for regulators and maintainable for future developers.

## Local-Only And CEII Rules

- Do not add cloud uploads, telemetry, remote crash reporting, or external logging.
- Do not send project inputs, GridPACK outputs, run manifests, or derived exports to online services. This includes
  hosted model APIs. A local model served on a loopback address by a user-installed CLI is not an online service;
  adapters for hosted providers must stay disabled and cannot be enabled in a normal feature PR.
- Keep Docker runs local and least-privilege by default. `--network none` and `--pull=never` are absolute rules for
  every container GridLens builds a command for. Mounts differ by container, and the difference is deliberate:
  - the GridPACK solver container mounts only the per-run `work/` directory;
  - the optional generated-analysis sandbox mounts the selected run directory read-only at `/run-data`, plus the
    reviewed script, under a pinned `sha256` image ID, non-root UID/GID, `--cap-drop ALL`, `no-new-privileges`, a
    read-only root filesystem, no GPU, and stdout-only output. See `docs/security_ceii.md` for why the whole run
    directory is in scope there.
- Agent inference must fail closed unless the endpoint resolves only to loopback. Never read, log, or export CLI
  credentials. Execute generated scripts only through the pinned, label-checked, network-free sandbox, and only after
  explicit per-script approval bound to the reviewed SHA-256 hash.
- Do not commit real CEII data, proprietary cases, local run folders, generated exports, agent session folders, or
  screenshots containing sensitive grid information.
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
- `analysis/` owns parsing, enrichment, metrics, graph caches, master exports, and distribution exports.
- `gui/` owns PySide6 widgets and view-specific adapters. Keep business rules in pure helper modules when possible.

Prefer small functions with clear names. Add a new helper module when it makes behavior reusable and testable. Avoid
large GUI event handlers that also validate data, build Docker requests, parse outputs, or write analysis artifacts.

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
