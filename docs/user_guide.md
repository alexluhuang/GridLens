# User Guide

## Create A Project

1. Open GridPACK Workbench.
2. Go to Project.
3. Enter a project name.
4. Choose a project folder.
5. Add the GridPACK input files.
6. Choose the XML configuration file.
7. Click `Create / Save Project`.

The app copies the selected files into `original_inputs/` in the project folder.

## Run GridPACK

1. Go to Run.
2. Confirm the Docker image.
3. Confirm the GridPACK executable, for example `ca.x` or `powerflow.x`.
4. Choose the MPI process count.
5. Click `Check Docker`.
6. Click `Run GridPACK`.

The live log appears in the Run tab. The run folder contains:

```text
manifest.json
status.json
work/
logs/run.log
reports/
```

The same terminal stream is also tee'd into `work/terminal.log`, so it appears with the run outputs in the Results tab and exported ZIPs.

## Review Outputs

Go to Results, choose a run, and review files written under `work/`.

Use `Export ZIP` to create a local package containing the run files.

## Generate Analysis

Go to Analysis, choose a run, and click `Generate Report`.

The app creates:

```text
reports/output_inventory.csv
reports/analysis_summary.json
reports/success_summary.svg
reports/report.html
exports/master.csv
exports/master_cleaned.csv
exports/outliers.csv
exports/distributions/
```

The branch master files merge available branch data from the RAW file and branch-related GridPACK TXT outputs. `master_cleaned.csv` removes utilization outliers and is used for subsequent distribution analysis.

Use the Analysis tab's Distributions view to select independent variables and generate layered violin plus box-and-whisker plots of transmission utilization. Each generated plot has a companion CSV table and displays the source code path used to produce it.
