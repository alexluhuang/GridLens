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

The **Agent** tab answers questions about completed runs in plain language. Typical questions are "where are
the most congested lines", "how did you run the contingency analysis", and "where are my files".

The agent is not the source of numerical truth. Every number in an answer comes from a GridLens function that
read your analysis cache, and the answer cites the call that produced it, such as `[T1]`. The Sources pane
lists those calls with the files each one read. A citation that does not match a recorded call is marked
invalid, so you can tell a real number from an invented one.

### Before you start

GridLens ships no model and no inference. Install the tools yourself:

1. Install Hermes Agent, following its own installation guide.
2. Install Ollama and start it, which serves models on `http://127.0.0.1:11434`.
3. Pull a model that supports tool calls, for example `ollama pull nemotron3:33b`.

Hosted runtimes appear in the **Runtime** list but stay disabled. Sending project data to an online model
conflicts with the local-only rule in [CEII security notes](security_ceii.md).

### Ask a question

1. Go to **Agent**.
2. Click **Check runtime**. GridLens reports the Hermes version, whether Ollama answers on loopback, and
   which models are installed. Signing in does not apply to local Ollama.
3. Choose a **Local model** and a **Completed run**. To compare two runs, also choose one under
   **Compare with**.
4. If the run has no current analysis cache, click **Build / refresh analysis**. To also enable
   per-contingency drill-down, select **Include contingency drill-down index** first. Indexing reads the
   whole flat result once and takes a few minutes on a multi-gigabyte run.
5. Type your question and click **Send**. **Stop** ends the turn and stops the model process.

Changing the runtime, model, project, or run selection starts a new conversation, because a session is bound
to the runs it was created with.

### Read the answer

The **Activity** pane shows which tools ran. The **Sources** pane shows each call, how many rows it returned,
whether the result was truncated, and the files it read.

Watch for two limits the agent reports rather than hides. Maximum loading covers every recorded case in the
cache, including the base case, so it is not a converged N-1-only number. Thermal margin is 100 minus maximum
utilization, in percentage points of line rating. It is not available transfer capability, spare generation,
or load-serving capacity, and calculating any of those needs a separate study.

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

Each conversation writes a folder under `<project>/agent/sessions/`. Click **Open session folder** to see the
transcript, the runtime events, the tool audit, and any proposed script. Click **Export session audit** for a
ZIP of the same record.

Treat both as sensitive. They contain your questions, the model's answers, and grid data drawn from the run.
