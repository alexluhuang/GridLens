# GridPACK ca-scalability-v2 CSV Flat Support

This document explains the changes made so GridLens can read output from
`pnnl/gridpack:ca-scalability-v2` when the GridPACK XML uses:

```xml
<outputFormat>csv_flat</outputFormat>
```

## What Changed

Older GridPACK output summarized many contingencies into one row per monitored
branch. The new `csv_flat` output writes one row for each monitored
branch-contingency pair. That means the raw output is much larger, but it also
preserves the detail needed for custom statistics later.

GridLens now detects and reads these three CSV shapes:

- `training_tiny_flat1.csv`: branch result rows. Each row has a contingency,
  monitored branch (`from_bus`, `to_bus`, `circuit_id`, optional `section`), and
  `loading_percent`.
- `training_tiny_convergence.csv`: one row per contingency event with
  convergence and status information.
- `training_tiny_buses.csv`: bus, voltage, area, zone, and owner labels used to
  attach human-readable context to branch results.

## How GridLens Uses The Files

The large branch result CSV is processed with a GPU-first backend:

1. GridLens tries `dask-cudf` first. This uses RAPIDS cuDF partitions and runs
   dataframe operations on the NVIDIA GPU.
2. If RAPIDS is not installed, GridLens falls back to CPU Dask.
3. If Dask is not installed or the Dask path fails, GridLens falls back to a
   Python streaming parser.

GridLens does not hold the whole branch-contingency file in memory to build the
existing charts and tables. The default CSV partition size is `256MB`, and the
default memory target for the csv-flat path is `160GB`, leaving headroom below a
192 GB DGX Spark unified-memory system. These defaults can be changed with:

```bash
export GRIDLENS_CSV_FLAT_BACKEND=auto
export GRIDLENS_CSV_FLAT_BLOCKSIZE=256MB
export GRIDLENS_CSV_FLAT_SCHEDULER=threads
export GRIDLENS_CSV_FLAT_MEMORY_TARGET=160GB
```

Use `GRIDLENS_CSV_FLAT_BACKEND=dask_cudf` on DGX Spark when you want
analysis to fail loudly instead of falling back if RAPIDS is missing. Use
`python` only for debugging.

The Analysis tab runs this parsing and summarization work in a background Qt
worker so the desktop event loop stays responsive while Dask/cuDF does the heavy
lifting. The generated status text and table notes record which backend was
used; if they say `CPU Dask backend`, RAPIDS was not active for that run.

For the user-facing analysis, GridLens groups the branch-contingency rows back
to branch-level summaries:

- base-case utilization;
- mean utilization across available rows;
- maximum observed utilization;
- contingency/event where the maximum utilization occurred;
- number of rows and overload rows for the monitored branch.

The important difference is that `loading_percent` is already a utilization
percentage. GridLens no longer divides that value by Rate C. The old text
output path still uses real-power flow divided by RAW Rate C, exactly as before.

The convergence CSV is used as the success/failure source when `success.txt` is
not present. `OK` rows count as successful. `DIVERGED`, `ISLANDED`, and
`SLACK_OVERLOAD` rows count as failures; islanded rows are also marked as
isolated warnings.

The bus CSV is used for bus names, voltage classes, and control-area names when
a RAW file is not available.

## Parquet Conversion

The full branch result CSV can be very large. GridLens now has an internal
parquet conversion path in `src/gridlens/analysis/csv_flat.py`.

When the optional analysis dependencies are installed, GridLens converts the
large csv-flat result file to:

```text
run/reports/parquet/<csv-file-name>/
```

Interactive graph generation skips parquet conversion so the user can see the
charts as soon as the reduced branch summaries are ready. The default
`build_run_analysis()` path still writes parquet for report/export workflows
unless a caller explicitly opts out.

The conversion also uses the GPU-first backend. On DGX Spark with RAPIDS
installed, `dask-cudf` reads the CSV in bounded partitions and writes parquet
with Snappy compression. If RAPIDS is not installed, CPU Dask plus PyArrow is
used. If Dask is not installed, GridLens still builds the normal charts from
streamed summaries and records a note in the analysis manifest explaining that
parquet conversion was skipped.

Install the full analysis stack with:

```bash
pip install -e ".[analysis]"
```

or install from:

```text
requirements-analysis.txt
```

For GPU acceleration on DGX Spark, install RAPIDS packages that match the
machine's Python and CUDA environment, especially cuDF and dask-cuDF. The
GridLens code imports them only when available, so non-DGX development machines
can keep using pandas and CPU Dask.

## User Workflow

1. Use the Run tab to set the Docker image to `pnnl/gridpack:ca-scalability-v2`.
2. Use `missing` or `always` as the Docker pull policy if the image is not
   already in Docker's local image store.
3. Use an XML file that sets `outputFormat` to `csv_flat`.
4. Run GridPACK normally.
5. Open the Analysis tab and generate the same GridLens summaries, charts,
   master CSVs, and distribution outputs.

The visible analysis remains branch-centered, but it is now built from the raw
branch-contingency data produced by `ca-scalability-v2`.
