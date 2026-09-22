# GridPACK ca-scalability-v2 CSV flat support

This document explains the changes that let GridLens read output from `pnnl/gridpack:ca-scalability-v2`
when the GridPACK XML uses:

```xml
<outputFormat>csv_flat</outputFormat>
```

## What changed

Older GridPACK output summarized many contingencies into one row per monitored branch. The `csv_flat` output
writes one row for each monitored branch-contingency pair. The raw output is much larger, and it keeps the
detail needed for custom statistics later.

GridLens detects and reads three CSV shapes:

- `training_tiny_flat1.csv`: branch result rows. Each row has a contingency, a monitored branch
  (`from_bus`, `to_bus`, `circuit_id`, and an optional `section`), and `loading_percent`.
- `training_tiny_convergence.csv`: one row per contingency event, with convergence and status information.
- `training_tiny_buses.csv`: bus, voltage, area, zone, and owner labels, which attach readable context to
  branch results.

## How GridLens uses the files

GridLens processes the large branch result CSV with a GPU-first backend:

1. In `auto` mode, it uses eager RAPIDS cuDF for files that fit under the configured memory target.
2. For larger files, it tries `dask-cudf` first, which uses RAPIDS cuDF partitions and runs dataframe
   operations on the NVIDIA GPU.
3. If the GPU backends are unavailable and you have acknowledged CPU fallback, it falls back to CPU Dask.
4. If Dask is missing or the Dask path fails, it falls back to a Python streaming parser.

GridLens does not hold the whole branch-contingency file in memory to build the charts and tables. The
default CSV partition size is `256MB`, and the default memory target for the csv-flat path is `160GB`, which
leaves headroom below a 192 GB DGX Spark unified-memory system. Change the defaults with:

```bash
export GRIDLENS_CSV_FLAT_BACKEND=auto
export GRIDLENS_CSV_FLAT_BLOCKSIZE=256MB
export GRIDLENS_CSV_FLAT_SCHEDULER=threads
export GRIDLENS_CSV_FLAT_MEMORY_TARGET=160GB
```

On DGX Spark, use `GRIDLENS_CSV_FLAT_BACKEND=dask_cudf` when you want analysis to fail loudly instead of
falling back if RAPIDS is missing. Use `python` only for debugging.

The **Branch Analysis** and **Transformer Analysis** tabs run this parsing and summarization in a background
Qt worker, so the desktop event loop stays responsive while Dask and cuDF do the heavy lifting. If only CPU
Dask is available, the GUI warns you before it sets the acknowledgement that CPU fallback needs. The status
text and the table notes record which backend ran. If they say `CPU Dask backend`, RAPIDS was not active for
that run.

For the user-facing analysis, GridLens groups the branch-contingency rows back into branch-level summaries:

- Base-case utilization.
- Mean utilization across the available rows.
- Maximum observed utilization.
- The contingency or event where that maximum occurred.
- The number of rows and the number of overload rows for the monitored branch.

One difference matters more than the rest: `loading_percent` is already a utilization percentage, so
GridLens does not divide it by Rate C. The older text output path still uses real-power flow divided by RAW
Rate C.

GridLens uses the convergence CSV as the success and failure source when `success.txt` is absent. `OK` rows
count as successful. `DIVERGED`, `ISLANDED`, and `SLACK_OVERLOAD` rows count as failures, and islanded rows
are also marked as isolated warnings.

It uses the bus CSV for bus names, voltage classes, and control-area names when no RAW file is available.

## Derived artifacts

The same pass that aggregates the flat CSV also writes a compact contingency summary alongside the other
interactive tables:

```text
run/reports/interactive_tables/contingency_summary.csv
```

Each row is one event, with `event_idx`, `contingency`, `monitored_facility_count`, `violation_count`,
`max_loading_pct`, `worst_facility_key`, `converged`, and `status_code`. That is thousands of rows rather
than tens of millions, so ranking contingencies never reopens the flat result.

## Parquet conversion

The full branch result CSV can be very large. GridLens has an internal Parquet conversion path in
`src/gridlens/analysis/csv_flat.py`.

When the optional analysis dependencies are installed, GridLens converts the large csv-flat result file to:

```text
run/reports/parquet/<csv-file-name>/
```

Interactive graph generation skips Parquet conversion, so you see the charts as soon as the reduced branch
summaries are ready. The default `build_run_analysis()` path still writes Parquet for full artifact and
export workflows unless a caller opts out.

The conversion also uses the GPU-first backend. On DGX Spark with RAPIDS installed, `dask-cudf` reads the
CSV in bounded partitions and writes Parquet with Snappy compression. Without RAPIDS, GridLens uses CPU Dask
and PyArrow. Without Dask, it still builds the normal charts from streamed summaries and records a note in
the analysis manifest explaining that it skipped Parquet conversion.

### The contingency drill-down index

The Agent tab can build a second, separate Parquet tree for per-contingency and per-branch drill-down:

```text
run/reports/event_index/
  manifest.json
  <generation>/bucket-00.parquet … bucket-63.parquet
```

This one is built by `src/gridlens/analysis/event_index.py`, not by the conversion path above. It streams
the flat CSV through PyArrow, buckets rows by `event_idx` into 64 files, and compresses with zstd. It
publishes `manifest.json` only after a complete build, and the manifest records the size and modification
time of the source CSV, so GridLens can detect a stale index and refuse to query it.

On the 8.7 GB reference run, that build indexed 74,701,440 rows in about 101 seconds, produced 3.1 GB of
Parquet, and peaked at 2.0 GB of host memory. A single-contingency query against the result returns in under
0.1 seconds. Bucketing was chosen over a sorted or unpartitioned layout after measuring all three: it builds
fastest, queries fastest, and uses half the peak memory, at the cost of about 24% more disk.

Install the full analysis stack with:

```bash
pip install -e ".[analysis]"
```

Or install from:

```text
requirements-analysis.txt
```

For GPU acceleration on DGX Spark, install the RAPIDS packages that match the machine's Python and CUDA
environment, especially cuDF and dask-cuDF. GridLens imports them only when they are available, so a non-DGX
development machine can keep using pandas and CPU Dask.

## User workflow

1. In the Run tab, set the Docker image to `pnnl/gridpack:ca-scalability-v2`.
2. If the image is not already in Docker's local image store, set the Docker pull policy to `missing` or
   `always`.
3. Use an XML file that sets `outputFormat` to `csv_flat`.
4. Run GridPACK normally.
5. Open **Branch Analysis** or **Transformer Analysis** and generate the interactive summaries and charts.

The visible analysis stays branch-centered, and it is built from the raw branch-contingency data that
`ca-scalability-v2` produces. Master CSVs and distribution outputs remain available through the analysis
export helper functions for developer and API workflows.
