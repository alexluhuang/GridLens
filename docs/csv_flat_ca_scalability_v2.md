# GridPACK ca-scalability-v2 CSV Flat Support

This document explains the changes made so GridPACK Workbench can read output from
`pnnl/gridpack:ca-scalability-v2` when the GridPACK XML uses:

```xml
<outputFormat>csv_flat</outputFormat>
```

## What Changed

Older GridPACK output summarized many contingencies into one row per monitored
branch. The new `csv_flat` output writes one row for each monitored
branch-contingency pair. That means the raw output is much larger, but it also
preserves the detail needed for custom statistics later.

GridPACK Workbench now detects and reads these three CSV shapes:

- `training_tiny_flat1.csv`: branch result rows. Each row has a contingency,
  monitored branch (`from_bus`, `to_bus`, `circuit_id`, optional `section`), and
  `loading_percent`.
- `training_tiny_convergence.csv`: one row per contingency event with
  convergence and status information.
- `training_tiny_buses.csv`: bus, voltage, area, zone, and owner labels used to
  attach human-readable context to branch results.

## How Workbench Uses The Files

The large branch result CSV is streamed. Workbench does not need to hold the
whole file in memory to build the existing charts and tables.

For the user-facing analysis, Workbench groups the branch-contingency rows back
to branch-level summaries:

- base-case utilization;
- mean utilization across available rows;
- maximum observed utilization;
- contingency/event where the maximum utilization occurred;
- number of rows and overload rows for the monitored branch.

The important difference is that `loading_percent` is already a utilization
percentage. Workbench no longer divides that value by Rate C. The old text
output path still uses real-power flow divided by RAW Rate C, exactly as before.

The convergence CSV is used as the success/failure source when `success.txt` is
not present. `OK` rows count as successful. `DIVERGED`, `ISLANDED`, and
`SLACK_OVERLOAD` rows count as failures; islanded rows are also marked as
isolated warnings.

The bus CSV is used for bus names, voltage classes, and control-area names when
a RAW file is not available.

## Parquet Conversion

The full branch result CSV can be very large. Workbench now has a parquet
conversion path modeled on the scripts cloned at:

```text
third_party/GridPACK-file-conversion/
```

When the optional analysis dependencies are installed, Workbench converts the
large csv-flat result file to:

```text
run/reports/parquet/<csv-file-name>/
```

The conversion uses Dask plus PyArrow with Snappy compression. If those optional
dependencies are not installed, Workbench still builds the normal charts from
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

## User Workflow

1. Use the Run tab to set the Docker image to `pnnl/gridpack:ca-scalability-v2`.
2. Use `missing` or `always` as the Docker pull policy if the image is not
   already in Docker's local image store.
3. Use an XML file that sets `outputFormat` to `csv_flat`.
4. Run GridPACK normally.
5. Open the Analysis tab and generate the same Workbench summaries, charts,
   master CSVs, and distribution outputs.

The visible analysis remains branch-centered, but it is now built from the raw
branch-contingency data produced by `ca-scalability-v2`.
