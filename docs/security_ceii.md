# CEII security notes

GridLens runs locally with CEII data. It has no cloud services, no telemetry, no external crash reports, and
no remote logging.

GridLens ships no model, no inference engine, and no provider credentials, and it never signs a user in.
The optional Agent tab drives the Hermes Agent CLI, only against an inference endpoint that resolves to
loopback. Hosted providers are disabled in this build.

When Hermes Agent, Ollama, or a model is missing, the Agent tab offers to install it, and installs nothing
until the user agrees. It downloads Hermes's official installer from hermes-agent.nousresearch.com and runs
it at the one validated commit, downloads Ollama from ollama.com into the user's data folder, and has the
local Ollama service pull models from the Ollama library. These downloads send no project data. On a
machine that must stay offline, install the three from approved media beforehand; GridLens then finds them
and downloads nothing.

## Defaults

- Docker run network mode is `none`.
- Docker pull policy is `never`.
- Two containers exist, and they mount different things. The GridPACK solver container mounts only the
  per-run `work/` folder. The optional generated-analysis sandbox mounts the selected run folder read-only at
  `/run-data`. For why, and for the rest of its confinement, see [Generated scripts](#generated-scripts).
- GridLens never mounts the user's home directory.
- Every run records input SHA-256 hashes in `manifest.json`.
- Outputs stay in the local project folder.

## AI planning agent

The Agent tab is optional. These controls apply when someone uses it.

- GridLens verifies the route before any project text, path, tool schema, or tool result reaches the
  runtime. The endpoint host has to resolve exclusively to loopback. HTTP redirects are refused, proxies are
  neutralized through `NO_PROXY` and `no_proxy`, and an Ollama model that reports a remote host, a remote
  model, or a cloud tag is rejected. GridLens re-verifies the model at the start of every turn, so a model
  swapped to a cloud variant mid-session fails closed.
- GridLens tools return absolute paths and every matching row the model asks for. The copy sent to the
  model is bounded at 36,000 bytes: a larger result is saved whole in the session's `results/` folder, and
  the model reads it through the GridLens file tools. GridLens treats log lines, filenames, RAW labels,
  contingency names, and generated-script output as data, never as instructions.
- The GridLens file tools read files only inside GridLens project folders and the session folder, and
  never follow a symlink out of them. They can read every field of those files, including RAW cases and
  the full flat results. The reference document search reads only `<projects folder>/Reference documents/`,
  skips symlinks and hidden files, and treats document text as data, never as instructions.
- When an embedding model is installed in Ollama, the document search sends passages of the reference
  documents, and the question, to that model through the same loopback-only `ollama_json` call that refuses
  redirects, proxies, and models that report a remote host. Without one it uses BM25 alone and sends
  nothing. Its cache, `Reference documents/.gridlens-index/` (`0700`, files `0600`), holds the documents'
  text and embeddings, so a user who adds internal criteria there should treat the cache as they treat the
  documents.
- The agent can change projects. It can create a project and copy input files into it from any path the
  user can read, write the project's GridPACK XML, start and stop GridPACK runs, and build analyses. A run
  it starts uses the same Docker command builder and the Run tab's saved settings, so the saved network
  mode (`none` by default) and pull policy apply to it unchanged. If the saved pull policy is `missing` or
  `always`, an agent-started run can pull an image, just as a Run tab run can.
- The agent can run GridPACK on an edited copy of a project's RAW case (`start_sensitivity_run`). The
  project's case is never changed. Because the run studies a network the user has not reviewed, the first
  call only previews the edits, and the run starts only when the same call is repeated with `confirm=True`
  after the user has sent another message. The edited case and `sensitivity_changes.json` are written into
  the run's `work/` folder, and the run's manifest records their hashes.
- The CLI runs from a per-session profile inside the project, with a minimal environment: no bundled skills
  or plugins, no memory, no telemetry, no update checks, no lazy installs, no adoption of external logins,
  and only the GridLens MCP toolset exposed. The project root is never the CLI working directory, and no
  file or shell tool is enabled.
- Credentials stay with the vendor CLI. GridLens runs status probes only. It never reads, copies, logs, or
  exports a token.

### Session folders

Sessions live in `<projects folder>/Clarke conversations/<UTC timestamp>_<suffix>/`, outside any one
project, because one conversation can work in several. Sessions that earlier versions wrote to the hidden
`<projects folder>/.gridlens-agent/sessions/` are moved there when the Agent tab opens; older ones live in
`<project>/agent/sessions/`. They hold CEII-derived material, so treat them as CEII. Each session folder
holds:

- `context.json`, with the project root (or none) and the run IDs selected when the session started, the
  projects folder, the model, the endpoint, the runtime, and the route. It is written once.
- `focus.json`, once the user has moved the conversation to another project or other runs, with the project
  root and the run IDs of the latest turn. It never changes the route, the runtime, or the model.
- `prompts/<nanoseconds>.txt`, the exact prompt text handed to the CLI.
- `transcript.jsonl`, with the user's questions verbatim and the model's answers.
- `runtime_events.jsonl`, the normalized runtime event stream and captured diagnostics.
- `tool_calls.jsonl`, the append-only tool audit, which contains grid loading values and facility keys.
- `results/<call id>.json` and `results/<call id>.csv`, the complete copies of tool results too large to
  send inline.
- `usage.json` and `status.json`.
- `generated/*.py` and `generated/*.json`, proposed scripts and their review records.
- `generated/executions/*/script.py`, `result.json`, and `output.txt`, the approved bytes and the sandbox
  output.
- `script_executions.jsonl`.
- `conversation.md`, a readable copy of all of the above in order, including every tool result in full.

Directories are mode `0700` and files are mode `0600`. Session folders inherit the projects folder's
encryption, backup, retention, and deletion rules, so apply to the projects folder the rules its projects
need, and deleting a project does not delete the conversations about it. Nothing leaves the projects folder
unless the user chooses **Export session (ZIP)…**. That archive is an unencrypted ZIP written `0600`, it is a sensitive artifact, and it needs
the same handling as any other CEII material. Sessions persist until an operator deletes the folder, under
the same approved deletion procedure as run folders. Project-level `exports/` sits outside the session and
outside the mounted run folder.

### Agent jobs

A GridPACK run or an analysis build that the agent starts runs as a separate GridLens process, which keeps
running after the turn ends and after GridLens closes. Each job has a folder,
`<project>/agent/jobs/<job id>/`, holding `job.json` (the request, the conversation that started it, the
worker's process ID, and the job's state and result) and `job.log` (a timestamped history of the job and
anything the worker printed). Treat job folders as CEII, like session folders. To stop a job, ask the
agent to cancel it, or stop a run's container with `docker stop gridlens-<run id>`.

### Egress audit scope

The audit answers what GridLens handed to the runtime and what the runtime handed back. It does not answer
what bytes crossed the socket. It records the logical prompts, the tool schemas GridLens exposes, every tool
call with its arguments and its bounded result, the complete copy of any larger result, the runtime's event
stream, and the generated scripts and sandbox output. It cannot record fields the provider CLI adds on its
own, transport headers, retries or internal re-prompts inside the CLI, tokenization, or the exact network
bytes. Treat the audit as
authoritative for GridLens-controlled content and as incomplete for the wire. If you need byte-level egress
evidence, capture it at the host or network layer.

### Generated scripts

GridLens saves generated code for review and never executes it without per-script approval bound to the
reviewed SHA-256 hash. It snapshots the reviewed bytes, so editing the proposal afterward cannot change what
runs.

Execution uses a separately prepared image, identified by its immutable `sha256` image ID and carrying the
`org.gridlens.purpose=generated-analysis` label. The container runs with `--pull=never`, `--network none`,
`--read-only`, `--cap-drop ALL`, `no-new-privileges`, the invoking non-root UID and GID, and limits on CPU,
memory, pids, nofile, fsize, and CPU time. `NVIDIA_VISIBLE_DEVICES=void` hides the GPUs. Writes are confined
to `noexec` tmpfs mounts. Only two paths are bind-mounted, both read-only: the selected run folder at
`/run-data`, and the reviewed script. The only egress is stdout, capped at 256 KiB, and GridLens records
that output as untrusted.

Mounting the whole run folder rather than just `work/` is a distinct reviewed case. The questions this
feature exists to answer, such as "How did you run the contingency analysis?" and "Where are my files?",
need `logs/`, `manifest.json`, and `status.json`. The deterministic tools already expose those files to the
model, so a narrower mount would break the documented script contract without removing a data class the
agent can reach anyway. The mount is read-only and the container has no network, so the sandbox adds no
write path and no egress path to the run folder.

[Docker group risk](#docker-group-risk) applies to this container unchanged.

### Hosted inference

Hosted runtimes, meaning Codex and Claude Code, are prohibited. Their adapters ship disabled and stay
disabled.

`GRIDLENS_ALLOW_HOSTED_AGENT` is deliberately an operator action in the environment rather than a GUI
preference, so an ordinary feature change cannot relax the local-only rule by accident. Setting it is not an
authorization. Authorization is a written governance decision, recorded in this file and in
`CONTRIBUTING.md` before anyone sets the variable, and it has to define at least the following:

1. Which data classes may leave the machine, and which may not.
2. The approved providers and accounts, and the contractual terms covering them.
3. Provider-side retention, training use, and deletion commitments.
4. Data residency and any cross-border constraints.
5. Incident response, including who is notified and within what window when CEII reaches an unapproved
   destination.
6. Which administrators may set the variable, and how that is enforced and reviewed on deployed machines.

Until such a decision exists, treat any machine with `GRIDLENS_ALLOW_HOSTED_AGENT` set as misconfigured.

## Operational controls

Use these controls for regulated deployments:

1. Pull or load Docker images before you open CEII inputs.
2. Prepare and pin the generated-analysis sandbox image before you open CEII inputs. GridLens never pulls it.
3. Pin production image versions. Do not use `latest`.
4. Keep image tarballs and installers in an approved internal repository.
5. Disable automatic updates unless they are approved.
6. Store project folders on encrypted local storage.
7. Back up project folders through approved internal systems only.
8. Restrict Docker group membership to approved users.
9. Review any extra Docker arguments before use.
10. Leave `GRIDLENS_ALLOW_HOSTED_AGENT` unset, and audit for it.

## Docker group risk

Membership in the `docker` group gives a user root-equivalent control of the host through Docker. This is a
property of the Docker platform rather than a choice this app makes. In a CEII environment, get written
approval from the security owner before you rely on Docker group access.

## Future hardening

Production hardening should add:

- Signed installers.
- Signed container images.
- SBOM generation.
- Pinned Python dependency hashes.
- A local-only update mechanism.
- Explicit retention and deletion policies for runs and agent sessions.
- Parser validation against known GridPACK output schemas.
