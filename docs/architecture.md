# Architecture

GridLens separates the consumer GUI from the execution engine. The GUI gathers input files and settings. The
core layer creates a local project and run folder. The runner layer builds a Docker argument list and runs GridPACK. The
analysis layer reads local outputs and creates graph data and exports.

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

## Project Folders

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
```

The `original_inputs/` directory stores the project input files. Every run copies those files into that run's `work/`
directory. Docker sees only the run's `work/` directory, mounted at `/app/workspace`.

## Docker Boundary

GridPACK's Docker documentation describes `/app/workspace` as the working directory and shows `mpirun -n ...` inside the
container. This app follows that model and also adds security and reproducibility defaults:

- `--network none`
- `--pull=never`
- `--platform linux/amd64` or `linux/arm64`
- `-u uid:gid`
- `-e HOME=/tmp`
- `-v run/work:/app/workspace`
- `-w /app/workspace`

The command is built as a Python list and passed to `subprocess.Popen` without a shell. This avoids shell quoting
problems and command injection risks.

## Audit Files

Each run creates:

- `manifest.json`: image, executable, XML file, MPI process count, platform, input hashes, and exact Docker command.
- `status.json`: running/completed/failed state and return code.
- `logs/run.log`: command and streamed GridPACK output.
- `work/terminal.log`: the same streamed terminal output tee'd into the output folder.

## Analysis Layer

The analysis layer is deliberately local and file-based. It can:

- list output files;
- estimate success/failure counts from `success.txt`;
- parse, normalize, and enrich GridPACK outputs;
- write `reports/analysis_manifest.json` and reusable normalized tables under `reports/tables/`;
- write lightweight interactive chart caches under `reports/interactive_tables/`;
- write `exports/master.csv`, `exports/master_cleaned.csv`, and `exports/outliers.csv`;
- write distribution plot PNGs and companion CSV tables under `exports/distributions/`;
- export a run ZIP.

The GUI's `Generate Graphs` action calls the interactive analysis path. It first reuses a fresh
`reports/analysis_manifest.json` when one already exists; otherwise it writes only
`reports/interactive_analysis_manifest.json` and `reports/interactive_tables/`. Master CSVs and distribution plots are
created by the lower-level export helpers, not by the embedded graph button.

Analysis responsibilities are split by module:

- `parser_models.py`: defines shared parser data objects such as `ParsedTable`.
- `parsers.py`: converts GridPACK output files into normalized `ParsedTable` objects.
- `csv_flat.py`: detects `ca-scalability-v2` CSV flat outputs, streams branch-contingency rows into branch summaries, parses convergence and bus metadata CSVs, and prepares parquet conversion for the full branch result CSV.
- `table_schemas.py`: defines the expected columns and types for whitespace-delimited GridPACK TXT outputs.
- `raw_parsers.py`: parses RAW bus metadata and branch-like RAW metadata, including non-transformer branches and transformer-derived branch rows.
- `enrichment.py`: adds RAW-derived bus names, areas, zones, and voltage classes to parsed tables.
- `metrics.py`: computes decision-support metrics from already-parsed tables.
- `dataset.py`: orchestrates parsing, enrichment, metrics, table exports, and the analysis manifest.
- `interactive.py`: builds and caches the smaller data set used by the embedded Branch Analysis and Transformer Analysis graphs.
- `utilization.py`: defines which branch-like RAW records are included in utilization calculations.
- `master.py`: creates branch-level `master.csv`, `master_cleaned.csv`, and `outliers.csv`.
- `distributions.py`: creates utilization distribution tables and plots from `master_cleaned.csv`.
- `summary.py`: exports a selected run directory as a ZIP package.
- `gpu_pandas.py`: imports pandas through `cuDF.pandas` when RAPIDS is available, with a regular pandas fallback for development and tests.
- `table_helpers.py`: centralizes CSV-safe value conversion for table export.

The branch master and distribution exporters use `cuDF.pandas` when RAPIDS cuDF is available, then import pandas through
that accelerated layer. Development systems without cuDF fall back to pandas so the code remains testable.

See `docs/csv_flat_ca_scalability_v2.md` for a plain-language walkthrough of the `pnnl/gridpack:ca-scalability-v2`
CSV flat workflow.
