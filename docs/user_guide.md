# User guide

## Create a project

1. Open GridLens.
2. Go to **Project**.
3. Enter a project name.
4. Choose a project folder.
5. Add the GridPACK input files, including the network file such as a RAW file.
6. Click **Create / Save Project**.

The app copies the selected files into `original_inputs/` in the project folder.

## Generate the XML configuration

1. Go to **Configuration**.
2. Confirm the generated XML file name, usually `input.xml`.
3. Choose the network file.
4. Choose the contingency type, the contingency rating, and the reactive-power-limit setting.
5. If you need to change GridPACK defaults such as output format, voltage limits, monitor files, PETSc
   options, or powerflow settings, expand **Advanced Configuration**.
6. Click **Generate / Save XML**.

The app writes the XML configuration into `original_inputs/` and updates the project so the Run tab can use
it.

## Run GridPACK

1. Go to **Run**.
2. Confirm the Docker image.
3. Confirm the GridPACK executable, for example `ca.x` or `powerflow.x`.
4. Choose the MPI process count.
5. Click **Check Docker**.
6. Click **Run GridPACK**.

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

Go to **Results**, choose a run, and review the files written under `work/`.

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

For legacy TXT outputs, utilization metrics use the real-power flow from `pflow.txt` and `pflow_mm.txt`
divided by the RAW branch Rate C (`ratec`). For `ca-scalability-v2` csv-flat outputs, they use the reported
`loading_percent` directly. **Branch Analysis** covers non-transformer RAW branches. **Transformer Analysis**
covers two-winding transformer branches and synthetic three-winding transformer branch rows. Performance-index
outputs are not used as utilization metrics.

Developer and API workflows can create `exports/master.csv`, `exports/master_cleaned.csv`,
`exports/outliers.csv`, and `exports/distributions/` through the analysis export helpers. Those exports have
no separate GUI view yet.

## Ask the planning agent

The **Agent** tab is a planning agent you talk to in plain language. It can:

- answer questions about runs, such as "where are the most congested lines" or "how did you run the
  contingency analysis";
- read every field of every project file: RAW cases, the XML configuration, GridPACK CSV and text outputs,
  GridLens caches, logs, and manifests;
- set up and run studies, such as "create a project from /data/case.raw, run a full branch N-1, and list
  the lines above 100%". It creates the project, writes the XML, starts the GridPACK run, waits for it,
  and builds the branch and transformer analysis, using the same functions as the other tabs.

The agent is not the source of numerical truth. Every number in an answer comes from a GridLens function, and
the answer cites the call that produced it, such as `[T1]`. Open **Full activity and sources** to inspect those calls and the files
each one read. A citation that does not match a recorded call is marked invalid, so you can tell a real number
from an invented one.

### Before you start

GridLens ships no model and no inference. Install the tools yourself:

1. Install Hermes Agent, following its own installation guide.
2. Install Ollama and start it, which serves models on `http://127.0.0.1:11434`.
3. Pull a model that supports tool calls, for example `ollama pull nemotron3:33b`.

Codex and Claude Code can be selected to inspect their installation and sign-in status, but **Send** stays
unavailable under the current local-only rule in [CEII security notes](security_ceii.md). GridLens shows a
copyable CLI command when sign-in is needed, plus the provider's documentation link. It never installs a CLI,
installs a model, or handles your credentials. Codex also remains unavailable because this CLI version cannot
prove that its built-in file and shell tools are isolated from project data.

### Ask a question

1. Go to **Agent**.
2. GridLens checks the selected runtime when the tab opens. Expand **Session setup** to change the runtime,
   model, or run. **Check runtime** repeats the probe. The status
   shows the CLI version, route, installed models, and sign-in state when sign-in applies. Local Ollama needs
   no sign-in. Use the setup command and documentation shown below the status if something is missing.
3. Choose a **Local model**. If a project is open, you can also choose a run under **Start from run**, and
   a second one under **Compare with**. Both are optional. They tell the agent where to start, and it can
   still reach any run of any project. With no project open, the agent can list and create projects in the
   projects folder named in your settings.
4. If a run has no current analysis cache, click **Build / refresh analysis**, or ask the agent to build it.
   To also enable per-contingency drill-down, select **Include contingency drill-down index** first. Indexing
   reads the whole flat result once and takes a few minutes on a multi-gigabyte run.
5. Type your question and press **Enter** or click **Send**. Press **Shift+Enter** for a new line. **Stop**
   ends the turn and stops the model process.

Your messages, the agent's streamed answer, and its process steps appear in one scrolling conversation.
Expand a **Process** card to see tool names, arguments, audited row counts, truncation notices, and source
paths. If the selected CLI supplies reasoning text, it appears there too. Hermes currently does not expose
reasoning text through its event stream, so the card says when it is unavailable. Choose a saved session in
the conversation selector to replay its messages and available process events, then ask a follow-up in that
session. The selector stays on the active session after each turn. **New conversation** starts a fresh
session. Changing the runtime, model, project, or run selection also starts a new conversation.

### Let the agent run a study

The agent runs GridPACK the way the **Run** tab does: through Docker, with the settings the Run tab saved
last, such as the image, the MPI process count, and the pull policy, unless you ask for others. A run and an
analysis build take minutes, so the agent starts each one as a background job and waits for it. A job keeps
going after the turn ends, and even after GridLens closes; ask the agent about it in a later turn. When a turn
ends, the Results and Analysis tabs refresh their run lists, so a run the agent started appears there too.

Before it stops a run, replaces an input file, or changes a project's XML, the agent shows you what would
change and asks you to confirm, even when you asked for the change. GridLens enforces this: the first request
only returns a preview, such as each setting's old and new value and the XML diff, and the change is made
only if you reply to confirm. The answer ends with a note while a change is waiting for you.

### Read the answer

The **Activity** pane shows which tools ran and what each call asked for. The **Sources** pane shows each
call, its filters, error or warnings, how many rows it returned, whether more rows remain, and the files it
read. The answer lists consulted tool-call IDs when a model omits inline citations.

There is no limit on how many rows a result can have. The agent can ask for every matching row, or page
through them. A result too large to send to the model whole is saved complete in the session's `results/`
folder, as JSON and as CSV, and the agent reads that file with the file tools. Sources shows the path of the
saved result and how many of its rows were shown inline.

The agent answers with a few general tools whose parameters it fills in, chaining calls as it needs to.
`rank` sorts objects by one metric and returns each with the value it was sorted by: facilities (branches,
transformers, or both) by maximum, base-case, or mean loading, thermal margin, overload count, or rating;
contingencies by their maximum loading, overload count, or solution statistics; and cases, one facility in
one contingency from the drill-down index, by loading, MW, Mvar, MVA, end voltage, or angle difference.
`rank_groups` sorts groups such as control areas, voltage classes, or outages by one statistic of a metric:
the mean, median, minimum, maximum, standard deviation, variance, interquartile range, count, or sum. It
computes each statistic from every object in the group and reports how many it used. Both take qualifiers
that select objects first, such as a control area, an outage's area, or loading above 100%, and both can
compare one run with another. One control-area qualifier for each of two areas selects the tie lines between
them. Overload counts count cases at or above 100% loading; GridPACK's own violation flag, which mostly marks
the outaged branch itself, is not counted. `read_file` reads, groups, joins, or compares any project file, for
example to total load or generation by area from the RAW case, or to list every setting that differs between
two runs. For mean loading by
voltage group or control area, the answer states the facility scope, the number of facilities used, and
per-group counts.
For top-line control-area questions, GridLens reads the endpoint area labels in the ranked result and
lists both areas when a line crosses a boundary.

Watch for three limits the agent reports rather than hides. Maximum loading covers every recorded case in the
cache, including the base case, so it is not a converged N-1-only number. Thermal margin is 100 minus maximum
utilization, in percentage points of line rating. It is not available transfer capability, spare generation,
or load-serving capacity, and calculating any of those needs a separate study. A facility with no positive
rating in the case has unknown loading, even though GridPACK reports it as 0%.

### Review a generated script

When no built-in function fits your question, the agent can propose a Python script. It only saves the
script. Nothing runs until you approve it.

1. Click **Review scripts**.
2. Read the code and the stated purpose.
3. Paste the image ID of the analysis sandbox, prepared as described in `packaging/agent/README.md`.
4. Click **Approve this script and run**.

The script runs with no network, no GPU, a read-only copy of the run, and CPU, memory, and time limits.
GridLens records the output as untrusted, because no GridLens function has checked it.

### Session files

Each conversation writes a folder under `<project>/agent/sessions/`, or under
`<projects folder>/.gridlens-agent/sessions/` when no project was open. Click **Open session folder** to see
the transcript, the runtime events, the tool audit, the saved results, and any proposed script. Click
**Export session audit** for a ZIP of the same record. Each background job has a folder under
`<project>/agent/jobs/` with its request, its status, and its output.

Treat all of these as sensitive. They contain your questions, the model's answers, and grid data drawn from
the run.
