# Contributing to GridLens

GridLens is meant to become an open-source desktop application for local GridPACK contingency analysis. Keep
your changes understandable for regulators and maintainable for the next developer.

## Local-only and CEII rules

- Do not add cloud uploads, telemetry, remote crash reporting, or external logging.
- Do not send project inputs, GridPACK outputs, run manifests, or derived exports to online services. That
  includes hosted model APIs. A local model served on a loopback address by a CLI the user installed is not an
  online service. Adapters for hosted providers stay disabled, and a normal feature pull request cannot enable
  them.
- Keep Docker runs local and least-privilege by default. `--network none` and `--pull=never` are absolute
  rules for every container GridLens builds a command for. Mounts differ by container, and the difference is
  deliberate:
  - The GridPACK solver container mounts only the per-run `work/` directory.
  - The optional generated-analysis sandbox mounts the selected run directory read-only at `/run-data`, plus
    the reviewed script. It runs under a pinned `sha256` image ID, a non-root UID and GID, `--cap-drop ALL`,
    `no-new-privileges`, a read-only root filesystem, no GPU, and stdout-only output. For why the whole run
    directory is in scope there, see [CEII security notes](docs/security_ceii.md).
- Agent inference has to fail closed unless the endpoint resolves only to loopback. Never read, log, or export
  CLI credentials. Execute a generated script only through the pinned, label-checked, network-free sandbox,
  and only after the user approves that exact SHA-256 hash.
- Do not commit real CEII data, proprietary cases, local run folders, generated exports, agent session
  folders, or screenshots that contain sensitive grid information.
- Use small synthetic fixtures in `tests/` and `samples/`.

## Development setup

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

Run the full suite before you submit a change:

```bash
python -m pytest
python -m compileall -q src tests
git diff --check
```

The test suite is deliberately focused. Add or update a test when you change parsing, analysis, Docker command
construction, project-folder behavior, GUI view-model logic, agent tools or runtime adapters, package
metadata, or documentation links.

### Opt-in agent checks

The default suite uses synthetic fixtures and makes no model calls. Run these separately when the matching
local dependency is available:

- `GRIDLENS_TEST_HERMES=1` tests the installed Hermes CLI against a synthetic loopback model server.
- `GRIDLENS_TEST_LOCAL_MODELS=1` runs a scored synthetic evaluation through installed Ollama models. Use
  `GRIDLENS_TEST_MODEL_NAMES=nemotron3:33b,gemma4:31b` to select models and
  `GRIDLENS_TEST_EVAL_OUTPUT=/tmp/model_evaluation.json` to retain the score file.
  Use `-k complete_voltage_groups` and `GRIDLENS_TEST_GROUP_EVAL_OUTPUT=/tmp/voltage_group_evaluation.json`
  for the separate full-population voltage-mean regression. Its report distinguishes a model-selected
  line-only scope from a scope corrected by the GridLens controller.
- `GRIDLENS_TEST_SAMPLE_PROJECT` and `GRIDLENS_TEST_SAMPLE_RUN` select a real, approved project/run for a
  read-only cache benchmark. The tool audit remains under pytest's temporary directory.
- `GRIDLENS_TEST_MCP_EXECUTABLE` checks the MCP entry point of a frozen executable.
- `GRIDLENS_TEST_SANDBOX_IMAGE` checks generated-script execution with a locally prepared, pinned image.

## Code organization

- `core/` owns settings, projects, validation, manifests, and the files of sensitivity runs.
- `psse/` owns the PSS/E RAW record layouts and the patcher that edits a case one field or line at a time.
  Keep its record layouts where GridPACK's block parsers read each field.
- `runner/` owns Docker probing, command construction, and process execution.
- `analysis/` owns parsing, enrichment, metrics, graph caches, master exports, and distribution exports.
- `agent/` owns the runtime adapter contract, the provider registry, sessions, the deterministic tools, the
  background jobs, and the MCP server. Nothing above the adapter layer may contain provider-specific code.
  Tools that operate GridLens call the same `core/`, `runner/`, and view-model functions as the tabs, so an
  agent-started run is built by the same Docker command builder as a Run tab run.
- `gui/` owns PySide6 widgets and view-specific adapters. Keep business rules in pure helper modules where you
  can.

Prefer small functions with clear names. Add a helper module when it makes behavior reusable and testable.
Avoid large GUI event handlers that also validate data, build Docker requests, parse outputs, or write
analysis artifacts.

## Style expectations

- Build Docker commands as argument lists. Never use `shell=True`.
- Validate paths, project names, Docker image names, executables, and MPI process counts that come from the
  user before you create run artifacts.
- Prefer explicit, readable Python over clever shortcuts.
- Document public functions and non-obvious helpers with short docstrings.
- Keep generated files, virtual environments, caches, and local project folders out of Git.

## Pull request checklist

- The app stays local-only and CEII-safe by default.
- New behavior has a focused test, or a clear reason you cannot test it automatically.
- `python -m pytest` passes.
- `python -m compileall -q src tests` passes.
- `git diff --check` reports no whitespace errors.
- The README or the docs are updated when workflow, packaging, security, or user-visible behavior changes.
