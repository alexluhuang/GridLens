# Architecture

GridLens separates the consumer GUI from the execution engine. The GUI gathers input files and settings. The
core layer creates a local project and run folder. The runner layer builds a Docker argument list and runs
GridPACK. The analysis layer reads local outputs and creates graph data and exports.

```text
PySide6 GUI
  -> core project manager
  -> Docker/GridPACK runner
  -> pnnl/gridpack Docker container
  -> local output files
  -> local analysis artifacts
  -> embedded Branch Analysis / Transformer Analysis graphs
  -> optional master CSV and distribution exports
```

The Agent tab is a second path over the same projects and runs:

```text
PySide6 Agent tab
  -> AgentController on a worker thread
  -> runtime adapter -> user-installed AI CLI subprocess
  -> GridLens MCP server (gridlens --mcp-server)
  -> deterministic tool service
       -> the same run artifacts, analysis caches, and project files
       -> the same project, configuration, and run functions as the other tabs
       -> background jobs (gridlens --agent-job) for GridPACK runs and analysis builds
  -> append-only session audit
```

## Project folders

A regulator-facing project is stored under:

```text
~/GridLensProjects/
  Project_Name/
    project.json
    original_inputs/
    runs/
      2026-06-12_15-30-22/
        manifest.json
        status.json
        work/
        logs/run.log
        reports/
        exports/          optional, created by analysis export helpers
    exports/
    agent/sessions/       optional, created by the Agent tab
```

The `original_inputs/` directory stores the project input files. Every run copies those files into that run's
`work/` directory. Docker sees only the run's `work/` directory, mounted at `/app/workspace`.

## Docker boundary

GridPACK's Docker documentation describes `/app/workspace` as the working directory and shows `mpirun -n ...`
inside the container. This app follows that model and adds security and reproducibility defaults:

- `--network none`
- `--pull=never`
- `--platform linux/amd64` or `linux/arm64`
- `-u uid:gid`
- `-e HOME=/tmp`
- `-v run/work:/app/workspace`
- `-w /app/workspace`

GridLens builds the command as a Python list and passes it to `subprocess.Popen` without a shell, which
avoids shell quoting problems and command injection.

## Audit files

Each run creates:

- `manifest.json`: image, executable, XML file, MPI process count, platform, input hashes, and the exact
  Docker command.
- `status.json`: running, completed, or failed state, and the return code.
- `logs/run.log`: the command and the streamed GridPACK output.
- `work/terminal.log`: the same streamed terminal output, copied into the output folder.

## Analysis layer

The analysis layer is deliberately local and file-based. It can do the following:

- List output files.
- Estimate success and failure counts from `success.txt`.
- Parse, normalize, and enrich GridPACK outputs.
- Write `reports/analysis_manifest.json` and reusable normalized tables under `reports/tables/`.
- Write lightweight interactive chart caches under `reports/interactive_tables/`.
- Write `exports/master.csv`, `exports/master_cleaned.csv`, and `exports/outliers.csv`.
- Write distribution plot PNGs and companion CSV tables under `exports/distributions/`.
- Export a run ZIP.

The GUI's **Generate Graphs** action calls the interactive analysis path. It reuses a fresh
`reports/analysis_manifest.json` when one already exists. Otherwise it writes only
`reports/interactive_analysis_manifest.json` and `reports/interactive_tables/`. The lower-level export
helpers create the master CSVs and the distribution plots, not the embedded graph button.

Analysis responsibilities split by module:

- `parser_models.py`: shared parser data objects such as `ParsedTable`.
- `parsers.py`: converts GridPACK output files into normalized `ParsedTable` objects.
- `csv_flat.py`: detects `ca-scalability-v2` CSV flat outputs, streams branch-contingency rows into branch
  summaries, parses convergence and bus metadata CSVs, and prepares Parquet conversion for the full branch
  result CSV.
- `table_schemas.py`: the expected columns and types for whitespace-delimited GridPACK TXT outputs.
- `raw_parsers.py`: parses RAW bus metadata and branch-like RAW metadata, including non-transformer branches
  and transformer-derived branch rows.
- `enrichment.py`: adds RAW-derived bus names, areas, zones, and voltage classes to parsed tables.
- `metrics.py`: computes decision-support metrics from parsed tables.
- `loading.py`: the shared utilization calculations. Both the GUI charts and the agent tools call these, so
  a number shown in a graph and the same number quoted by the agent come from one implementation.
- `utilization.py`: defines which branch-like RAW records count toward utilization.
- `contingencies.py`: builds the compact `contingency_summary` table during the same pass that aggregates
  the flat CSV, so ranking contingencies does not require re-reading the full result.
- `event_index.py`: builds and queries a bucketed Parquet index of the flat result, which is what makes
  per-contingency and per-branch drill-down affordable on a multi-gigabyte run.
- `dataset.py`: orchestrates parsing, enrichment, metrics, table exports, and the analysis manifest.
- `interactive.py`: builds and caches the smaller data set behind the embedded Branch Analysis and
  Transformer Analysis graphs.
- `service.py`: `AnalysisService`, the non-GUI build service that serializes and cancels analysis builds.
  The Analysis tab and the Agent tab share it, so two tabs cannot start competing builds.
- `progress.py`: phase-level progress updates for a build, as a picklable object that survives the queue
  back from the worker process.
- `master.py`: creates branch-level `master.csv`, `master_cleaned.csv`, and `outliers.csv`.
- `distributions.py`: creates utilization distribution tables and plots from `master_cleaned.csv`.
- `distribution_stats.py`: the per-group count, mean, and spread statistics behind those tables.
- `summary.py`: exports a selected run directory as a ZIP package.
- `gpu_pandas.py`: imports pandas through cuDF.pandas when RAPIDS is available, and falls back to regular
  pandas for development and tests.
- `table_helpers.py`: CSV-safe value conversion for table export.

The branch master and distribution exporters use cuDF.pandas when RAPIDS cuDF is available, then import
pandas through that accelerated layer. Development systems without cuDF fall back to pandas, so the code
stays testable.

For a plain-language walkthrough of the `pnnl/gridpack:ca-scalability-v2` CSV flat workflow, see
[the CSV flat scalability notes](csv_flat_ca_scalability_v2.md).

## Agent layer

The Agent tab is a planning agent. It answers questions about runs, reads every field of every project
file, and sets up and runs studies. The model never computes a number itself: it calls deterministic
GridLens functions, and the operation tools call the same functions as the Project, Configuration, Run, and
Analysis tabs.

GridLens supplies no inference. It detects a CLI that you installed, starts it as a subprocess, and hands it
one tool server.

- `agent/runtime.py`: the adapter contract. `RuntimeStatus`, `RuntimeEvent`, `PreparedRuntime`, and the
  `RuntimeAdapter` protocol. Nothing above this layer parses provider-specific output.
- `agent/providers.py`: the registry that maps a provider id to an adapter. Adding a runtime means adding a
  module and a row here, and touching nothing in the tool, session, controller, or GUI layers.
- `agent/hermes.py`: the Hermes adapter, for a local model served by Ollama on loopback. This is the
  validated runtime.
- `agent/claude_code.py` and `agent/codex.py`: the hosted adapters. Both stay disabled under the policy gate
  described in [CEII security notes](security_ceii.md).
- `agent/policy.py`: route classification. It resolves the inference endpoint and fails closed unless every
  resolved address is loopback.
- `agent/session.py`: the immutable session record. `SessionContext` records the open project (or none),
  the runs selected in the tab, the projects folder, the model, and the route. `find_project` and
  `resolve_run` turn project and run names into folders, and `scoped_path` rejects traversal and symlink
  escape.
- `agent/controller.py`: owns the conversation, runs one turn at a time under a deadline and byte caps,
  normalizes runtime events, and kills the whole process group on stop.
- `agent/tool_base.py`: what every tool shares. The result envelope, paging by offset and limit with no
  maximum row count, the saved complete copy of any result larger than the inline budget, stable error
  codes, provenance, and the paired audit records.
- `agent/tools.py`: the analysis tools over the compact caches, and `ToolService`, which combines every
  tool module. `TOOL_NAMES` lists the tools exposed over MCP.
- `agent/file_tools.py`: tools that list, describe, and read project files as tables, lines, or documents,
  including each section of a RAW case (read by `analysis/raw_sections.py`) and the full flat results.
- `agent/gridlens_tools.py`: tools that create projects, import inputs, write the GridPACK XML, start and
  stop runs, build analyses, and report background jobs.
- `agent/jobs.py`: background jobs. A GridPACK run or an analysis build runs as `gridlens --agent-job`, a
  separate process that outlives the turn and records its state under `<project>/agent/jobs/`.
- `agent/mcp_server.py`: serves those tools over stdio using the official MCP Python SDK, marking the tools
  that write. `main.py` dispatches `--mcp-server` and `--agent-job` before it imports Qt, so neither needs a
  GUI.
- `agent/scripts.py`: saves a model-proposed Python script for review, and runs an approved one in the
  pinned sandbox described in `packaging/agent/README.md`.

Each session writes an append-only record under `<project>/agent/sessions/<UTC timestamp>_<suffix>/`:
`context.json` for the session record, `manifest.json` for the runtime and command template,
`transcript.jsonl`, `runtime_events.jsonl`, `tool_calls.jsonl` for the tool audit and provenance, `results/`
for the complete copies of large results, `usage.json`, `status.json`, and `generated/` for any proposed
script. A session started with no project open lives in `<projects folder>/.gridlens-agent/sessions/`.
Every answer cites the call IDs from `tool_calls.jsonl`, and the GUI marks a citation that does not appear
there as invalid.
