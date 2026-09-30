# Clarke, the planning agent

Clarke is the planning agent in the **Agent** tab. You talk to it in plain language, and it can:

- answer questions about runs, such as "where are the most congested lines" or "how did you run the
  contingency analysis";
- read every field of every project file: RAW cases, the XML configuration, GridPACK CSV and text outputs,
  GridLens caches, logs, and manifests;
- set up and run studies, such as "create a project from /data/case.raw, run a full branch N-1, and list
  the lines above 100%". It creates the project, writes the XML, starts the GridPACK run, waits for it,
  and builds the branch and transformer analysis, using the same functions as the other tabs;
- compare runs, such as "compare this run with the one before it", by naming both in the question.

Clarke is not the source of numerical truth. Every number in an answer comes from a GridLens function, and
the answer cites the call that produced it, such as `[T1]`. Open **Full activity and sources** to inspect
those calls and the files each one read. A citation that does not match a recorded call is marked invalid,
so you can tell a real number from an invented one.

Clarke runs entirely on your computer. Your questions and your grid data never leave it.

## Set up Clarke

Clarke needs three things GridLens does not ship:

- **Hermes Agent**, the agent harness that drives the model and calls GridLens's tools. Clarke is
  validated with Hermes 0.21.4 only.
- **Ollama**, the inference engine that runs the model on this machine.
- **A model**, served by Ollama.

The first time you open the **Agent** tab, GridLens checks for all three. If Ollama is installed but not
running, GridLens starts it. If anything is missing, the **Set up Clarke** window opens. It says what is
installed and what GridLens will install, and nothing is downloaded until you press its install button:

- Hermes Agent 0.21.4 is installed with Hermes's official installer, from hermes-agent.nousresearch.com,
  into `~/.hermes/hermes-agent`, with the `hermes` command in `~/.local/bin`. The installer needs `git`. On
  Windows, its PowerShell installer puts Hermes in `%LOCALAPPDATA%\hermes` and fetches its own `git`.
- Ollama is downloaded from ollama.com into `~/.local/share/gridlens/ollama`, for your user account only, so
  no administrator password is needed. Unpacking it needs `zstd` (`sudo apt install zstd`). On a Jetson,
  Ollama's JetPack libraries are unpacked over it, as Ollama's own installer does. On Windows, Ollama's
  installer runs for your account, into `%LOCALAPPDATA%\Programs\Ollama`. An Ollama you installed yourself
  is used as it is.
- Models are downloaded from the Ollama library by the local Ollama service.

Choose models from the table. For each model it shows the developer, the total parameters, the active
parameters (those used for each word the model writes, which is fewer than the total for a
mixture-of-experts model), what the model can read besides text, its context length, and its download size.
**nemotron-3.5-lightning:latest** is the preferred model, marked with a star and checked for you. Clarke is
tuned and evaluated with it.

| Model | Developer | Total parameters | Active parameters | Modalities | Context | Download |
| --- | --- | --- | --- | --- | --- | --- |
| nemotron-3.5-lightning:latest (preferred) | NVIDIA | 30B | 3B | Text | 1M | 25 GB |
| nemotron-3-super:120b | NVIDIA | 120B | 12B | Text | 256K | 86 GB |
| nemotron3:33b | NVIDIA | 33B | 3B | Text, image, video, audio | 128K | 27 GB |
| gpt-oss:120b | OpenAI | 117B | 5.1B | Text | 128K | 65 GB |
| gpt-oss:20b | OpenAI | 21B | 3.6B | Text | 128K | 13 GB |
| gemma4:31b | Google | 31B | 31B | Text, image | 256K | 19 GB |
| gemma4:e4b | Google | 8B | 4B | Text, image, audio | 128K | 9.6 GB |
| muse-glimmer:30b | Meta | 30B | 30B | Text, image | 128K | 18 GB |
| granite4.2:30b | IBM | 29B | 29B | Text | 128K | 17 GB |
| granite4.2:8b | IBM | 8.8B | 8.8B | Text | 128K | 5.3 GB |

A large model needs as much free memory as its download size, or more. Each download takes minutes to tens
of minutes. The window shows its progress and a log, and **Cancel** stops it.

Later, the models you installed are listed under **Local model** in **Session setup**. To install or remove
models, choose **Install or remove models…** at the bottom of that list. It opens the same window: check a
model to install it, and uncheck an installed one to remove it. GridLens asks before it removes a model.

If Clarke stops working, for example because Ollama was stopped, the Agent tab says what is wrong and offers
**Set up Clarke…**.

## Ask a question

1. Go to **Agent**.
2. Optionally open a project in the **Project** tab. Clarke starts from that project and from the run
   selected in the **Results** tab, or its newest completed run. The line above the conversation says
   where the next question starts. Clarke can still reach any run of any project: name it in the question.
   With no project open, Clarke can list and create projects in the projects folder named in your settings.
3. Type your question and press **Enter** or click **Send**. Press **Shift+Enter** for a new line. **Stop**
   ends the turn and stops the model.

Your messages, Clarke's answer, and its process steps appear in one conversation. Answers are formatted:
headings, lists, tables, and code show as they would in a document. While Clarke is writing, you can scroll
back through the conversation; it follows the new text again once you scroll to the bottom. Expand a
**Process** card to see tool names, arguments, audited row counts, truncation notices, and source paths.

Choose a saved conversation in the list above the conversation to replay it, then ask a follow-up. The list
holds the conversations of every project, newest first, by the time each started and its first question.
**New conversation** starts a fresh one. Changing the model also starts a new conversation.

A conversation is not tied to one project or run. Open another project, or select another run in
**Results**, and the conversation stays; your next question goes to the project and run shown then. So you
can ask Clarke to create and run a study, open the new project in the **Project** tab, and carry on in the
same conversation.

**Session setup** holds the runtime, the model, a link to this page, and the session's buttons. The Claude
Code and Codex runtimes are listed but are under development and currently unavailable.

## Let Clarke run a study

Clarke runs GridPACK the way the **Run** tab does: through Docker, with the settings the Run tab saved last,
such as the image, the MPI process count, and the pull policy, unless you ask for others. A run and an
analysis build take minutes, so Clarke starts each one as a background job and waits for it. A job keeps
going after the turn ends, and even after GridLens closes; ask Clarke about it in a later turn. When a turn
ends, the Results and Analysis tabs refresh their run lists, so a run Clarke started appears there too.

A run's results have to be prepared for analysis before Clarke can read loadings from them. A run that
completes, whether Clarke or the **Run** tab started it, is prepared by itself: Clarke's run job goes on to
build the branch and transformer analysis once GridPACK finishes. For an older run, ask Clarke to prepare
it, or use **Generate Graphs** in the Branch or Transformer Analysis tab. Questions about single
contingencies also need the drill-down index; ask Clarke to build it.

Before it stops a run, replaces an input file, or changes a project's XML, Clarke shows you what would change
and asks you to confirm, even when you asked for the change. GridLens enforces this: the first request only
returns a preview, such as each setting's old and new value and the XML diff, and the change is made only if
you reply to confirm. The answer ends with a note while a change is waiting for you.

## Read the answer

The **Activity** pane shows which tools ran and what each call asked for. The **Sources** pane shows each
call, its filters, error or warnings, how many rows it returned, whether more rows remain, and the files it
read. The answer lists consulted tool-call IDs when a model omits inline citations.

There is no limit on how many rows a result can have. Clarke can ask for every matching row, or page through
them. A result too large to send to the model whole is saved complete in the session's `results/` folder,
as JSON and as CSV, and Clarke reads that file with the file tools. Sources shows the path of the saved
result and how many of its rows were shown inline.

Clarke answers with a few general tools whose parameters it fills in, chaining calls as it needs to. `rank`
sorts objects by one metric and returns each with the value it was sorted by: facilities (branches,
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
two runs. For mean loading by voltage group or control area, the answer states the facility scope, the
number of facilities used, and per-group counts. For top-line control-area questions, GridLens reads the
endpoint area labels in the ranked result and lists both areas when a line crosses a boundary.

Watch for three limits Clarke reports rather than hides. Maximum loading covers every recorded case in the
cache, including the base case, so it is not a converged N-1-only number. Thermal margin is 100 minus maximum
utilization, in percentage points of line rating. It is not available transfer capability, spare generation,
or load-serving capacity, and calculating any of those needs a separate study. A facility with no positive
rating in the case has unknown loading, even though GridPACK reports it as 0%.

## Review a proposed script

When no built-in function fits your question, Clarke can propose a Python script. It only saves the script.
Nothing runs until you approve it. **Review proposed scripts** in **Session setup** is available once the
conversation has proposed one, and shows how many.

1. Click **Review proposed scripts**.
2. Read the code and the stated purpose.
3. Paste the image ID of the analysis sandbox, prepared as described in `packaging/agent/README.md`.
4. Click **Approve this script and run**.

The script runs with no network, no GPU, a read-only copy of the run, and CPU, memory, and time limits.
GridLens records the output as untrusted, because no GridLens function has checked it.

## Conversation files

Each conversation has a folder in `<projects folder>/Clarke conversations/`, named by the time it started.
Click **Open session folder** to open it. `conversation.md` is the complete record, in order: each question,
each tool call with its arguments and full result, each background job started, each error, and each
answer. GridLens rewrites it after every turn. The other files are the machine-readable audit it is written
from:

- `transcript.jsonl`: each question and answer;
- `tool_calls.jsonl`: each tool call, with its arguments and complete result;
- `runtime_events.jsonl`: everything the runtime reported, including the answer as it was written;
- `results/`: complete results too large to send to the model;
- `generated/`: proposed scripts, and the output of those you ran;
- `prompts/`: the exact text sent to the model for each question;
- `runtime/`: the private Hermes profile GridLens builds for the conversation;
- `context.json`, `focus.json`, `manifest.json`, `status.json`, `usage.json`: the model and runtime, the
  project and run in focus, the launch command, the state of the last turn, and the token counts.

Click **Export session (ZIP)…** to save the conversation's folder, without the Hermes profile, as one ZIP
file to share or archive.

Conversations saved by earlier versions of GridLens in the hidden `<projects folder>/.gridlens-agent/sessions/`
folder are moved into `Clarke conversations/` the first time the Agent tab opens. Those saved under
`<project>/agent/sessions/` stay there and are listed when that project is open.

Each background job has a folder, `<project>/agent/jobs/<job id>/`, with two files: `job.json`, what was
asked, which conversation asked for it, and where the job stands, and `job.log`, a timestamped history of
the job, including any error.

Treat all of these as sensitive. They contain your questions, Clarke's answers, and grid data drawn from
your runs.
