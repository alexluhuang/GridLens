# User Guide

## Create A Project

1. Open GridLens.
2. Go to Project.
3. Enter a project name.
4. Choose a project folder.
5. Add the GridPACK input files, including the network file such as a RAW file.
6. Click `Create / Save Project`.

The app copies the selected files into `original_inputs/` in the project folder.

## Generate The XML Configuration

1. Go to Configuration.
2. Confirm the generated XML file name, usually `input.xml`.
3. Choose the network file.
4. Choose the contingency type, contingency rating, and reactive-power-limit setting.
5. Expand `Advanced Configuration` only if you need to change GridPACK defaults such as output format, voltage limits,
   monitor files, PETSc options, or powerflow settings.
6. Click `Generate / Save XML`.

The app writes the XML configuration into `original_inputs/` and updates the project so the Run tab can use it.

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
A run-level `exports/` directory may appear later if analysis export helpers create master CSVs or distribution outputs.

### Running ca-scalability-v2

To use the newer GridPACK container, enter this image in the Run tab:

```text
pnnl/gridpack:ca-scalability-v2
```

If the image is not already installed in Docker's local image store, set Docker
pull policy to `missing` or `always`. In Configuration, expand `Advanced Configuration` and set Contingency
`Output format` to `csv_flat` before clicking `Generate / Save XML`.

## Review Outputs

Go to Results, choose a run, and review files written under `work/`.

Use `Export ZIP` to create a local package containing the run files.

## Generate Analysis Graphs

Go to `Branch Analysis` or `Transformer Analysis`, choose a run, and click `Generate Graphs`.

If no fresh cache exists, the graph workflow creates:

```text
reports/interactive_analysis_manifest.json
reports/interactive_tables/
```

It can also reuse an existing full analysis cache at `reports/analysis_manifest.json` and `reports/tables/` when that
cache is current. The embedded graph button does not create master CSVs or distribution plots.

For legacy TXT outputs, utilization metrics use real-power flow from `pflow.txt` and `pflow_mm.txt` divided by RAW
branch Rate C (`ratec`). For `ca-scalability-v2` csv-flat outputs, utilization metrics use the provided
`loading_percent` directly. `Branch Analysis` includes non-transformer RAW branches. `Transformer Analysis` includes
two-winding transformer branches and synthetic three-winding transformer branch rows. Performance-index outputs are not
used as utilization metrics.

Developer/API workflows can create `exports/master.csv`, `exports/master_cleaned.csv`, `exports/outliers.csv`, and
`exports/distributions/` through the analysis export helpers. Those exports are not currently exposed as a separate GUI
view.
