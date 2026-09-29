# User guide

## Create a project

1. Open GridLens.
2. Go to **Project**.
3. Enter a project name.
4. Choose a project folder.
5. Add the GridPACK input files, including the network file such as a RAW file. You can also add a GridPACK
   XML configuration you already have.
6. Click **Create / Save Project**.

The app copies the selected files into `original_inputs/` in the project folder.

If you add a GridPACK XML configuration, the project uses it, and the file list marks it
**GridPACK configuration**. A project with no configuration yet adopts the one you add; if you add several,
GridLens asks which one to use, and if the project already has one, GridLens asks whether to switch. A
contingency-list XML is an input, not a configuration. If you add a file with the same name as one the
project already has, such as your own `input.xml` over the generated one, GridLens asks whether to replace it.

## Generate the XML configuration

1. Go to **Configuration**.
2. Confirm the generated XML file name, usually `input.xml`.
3. Choose the network file.
4. Choose the contingency type, the contingency rating, and the reactive-power-limit setting.
5. If you need to change GridPACK defaults such as output format, voltage limits, monitor files, PETSc
   options, or powerflow settings, expand **Advanced Configuration**.
6. Click **Generate / Save XML**.

The app writes the XML configuration into `original_inputs/` and updates the project so the Run tab can use
it. When the XML file already exists, for example one you added in the **Project** tab, GridLens edits it in
place: it changes the settings shown in this tab and keeps every other element, attribute, and comment. It
refuses to overwrite an XML file that is not a GridPACK configuration, such as a contingency list; choose
another file name instead.

## Run GridPACK

1. Go to **Run**.
2. Confirm the Docker image.
3. Choose the MPI process count.
4. Click **Check Docker**.
5. Click **Run GridPACK**.

GridLens runs GridPACK's contingency analysis, `ca.x`, with the container's network disabled, the Docker
platform flag matching this machine, and output files written as your user.

The live log appears in the Run tab. The run folder contains:

```text
manifest.json
status.json
work/
logs/run.log
reports/
```

GridLens also copies the same terminal stream into `work/terminal.log`, so it appears with the run outputs in
the Results tab and in exported ZIPs. A run-level `exports/` directory appears later if the analysis export
helpers create master CSVs or distribution outputs.

### Running ca-scalability-v2

To use the newer GridPACK container, enter this image in the Run tab:

```text
pnnl/gridpack:ca-scalability-v2
```

If the image is not already in Docker's local image store, set the Docker pull policy to `missing` or
`always`. In **Configuration**, expand **Advanced Configuration** and set the contingency **Output format**
to `csv_flat` before you click **Generate / Save XML**.

## Run a sensitivity analysis

The **Sensitivity Analysis** tab runs what-if studies that need an edited RAW case: loads, generators, and
branches that are new, removed, or changed. It edits a copy of the case that the project's XML configuration
names, and never changes the project's case.

1. Generate the XML configuration first. Its network file must be a PSS/E RAW case of version 33, 34, or 35.
2. Go to **Sensitivity Analysis** and choose **Loads**, **Generators**, or **Branches**. Each row is a record,
   and each column is one of its RAW fields, in the order the case's version gives them. Hover over a column
   heading to see what the field holds. A grey value is one the file leaves out, which PSS/E assumes.
3. To find a record, type a bus number, an ID or circuit, or part of a bus name in the filter box.
4. To change a field, double-click its cell and type the new value. A changed cell turns yellow, and its
   tooltip gives the old value.
5. To add a record, click **Add…** and enter its bus number, or a branch's from and to bus numbers. The new
   row takes PSS/E's defaults: the next free ID or circuit, the bus's area, zone, and owner, and, for a
   generator, the case's system base as its machine base. Give a new branch its reactance X.
6. To remove records, select their rows and click **Remove / Restore**. Click it again to restore them.
7. Click **Run N-1 Analysis**. The run starts in the **Run** tab, with its container settings, and appears in
   **Results** like any other run.

GridLens refuses an edit that GridPACK cannot read: a number in the wrong form, text with quotes, commas, or
slashes, a record at a bus the case does not have, two records with the same buses and ID, or a branch with
zero reactance. It warns before it runs a generator that is in service at a load bus (type 1), because
GridPACK holds such a generator at its PG and QG instead of letting it regulate voltage. A column heading also
says when GridPACK does not read a field, such as a load's owner or distributed generation.

A sensitivity run's `work/` folder holds three more files than a normal run:

```text
<case>_sensitivity.raw     the edited case, which GridPACK reads
<xml>_sensitivity.xml      the project's XML configuration, naming the edited case
sensitivity_changes.json   each edit, with the old and new values
```

The edited case differs from the base case only where you edited it. Unchanged fields keep their text and
spacing, a removed record loses its line, and a new record goes at the end of its section. **Save Edited
Case…** writes the same case to a file you choose, for example to open in PSS/E. **Discard Edits** undoes every
edit. The tab keeps your edits while you run them, so you can change a value and run again.

## Review outputs

Go to **Results**, choose a run, and review the files written under `work/`, with their sizes.

Click **Export ZIP** to create a local package of the run files.

## Generate analysis graphs

Go to **Branch Analysis** or **Transformer Analysis**, choose a run, and click **Generate Graphs**.

If no fresh cache exists, the graph workflow creates:

```text
reports/interactive_analysis_manifest.json
reports/interactive_tables/
```

It reuses an existing full analysis cache at `reports/analysis_manifest.json` and `reports/tables/` when that
cache is current. The embedded graph button does not create master CSVs or distribution plots.
[Analysis notes](analysis_notes.md) describes which files are read, how facilities are filtered, and how
utilization is calculated.

For legacy TXT outputs, utilization metrics use the real-power flow from `pflow.txt` and `pflow_mm.txt`
divided by the RAW branch Rate C (`ratec`). For `ca-scalability-v2` csv-flat outputs, they use the reported
`loading_percent` directly. **Branch Analysis** covers non-transformer RAW branches. **Transformer Analysis**
covers two-winding transformer branches and synthetic three-winding transformer branch rows. Performance-index
outputs are not used as utilization metrics.

Developer and API workflows can create `exports/master.csv`, `exports/master_cleaned.csv`,
`exports/outliers.csv`, and `exports/distributions/` through the analysis export helpers. Those exports have
no separate GUI view yet.

## Ask Clarke, the planning agent

The **Agent** tab is Clarke, a planning agent you talk to in plain language. It answers questions about any
project file, and it can set up projects, configure and start runs, and build analyses for you. Clarke runs
entirely on your computer; the first time you open the tab, GridLens offers to install what it needs. See
[Clarke, the planning agent](clarke.md) for how to set it up, ask questions, and read its answers.
