# CEII Security Notes

This project is designed for local-only operation with CEII data. It does not include cloud services, telemetry, external crash reports, or remote logging.

GridLens ships no model, no inference engine, and no provider credentials, and never installs a CLI or signs a user in. The optional Agent tab drives a CLI the user installed themselves, and only against an inference endpoint that resolves to loopback. Hosted providers are disabled in this build.

## Defaults

- Docker run network mode is `none`.
- Docker pull policy is `never`.
- Two different containers exist, and they mount different things. The GridPACK solver container mounts only the
  per-run `work/` folder. The optional generated-analysis sandbox mounts the selected run folder read-only at
  `/run-data`; see [Generated Scripts](#generated-scripts) for why, and for the rest of its confinement.
- The user's home directory is never mounted.
- Every run records input SHA-256 hashes in `manifest.json`.
- Outputs remain in the local project folder.

## AI Planning Agent

The Agent tab is optional. When it is used, the following controls apply.

- Route verification happens before any project text, path, tool schema, or tool result reaches the runtime. The
  endpoint host must resolve exclusively to loopback, HTTP redirects are refused, proxies are neutralized through
  `NO_PROXY`/`no_proxy`, and an Ollama model that reports a remote host, a remote model, or a cloud tag is rejected.
  The model is re-verified at the start of every turn, so a model swapped to a cloud variant mid-session fails closed.
- The model receives only bounded, capped tool results and run-relative paths. Log lines, filenames, RAW labels,
  contingency names, and generated-script output are treated as data, never as instructions.
- The CLI runs from a per-session profile inside the project with a minimal environment: no bundled skills or plugins,
  no memory, no telemetry, no update checks, no lazy installs, external logins not adopted, and only the GridLens MCP
  toolset exposed. The project root is never the CLI working directory, and no file or shell tool is enabled.
- Credentials stay owned by the vendor CLI. GridLens runs status probes only, and never reads, copies, logs, or
  exports tokens.

### Session Folders

Sessions live in `<project>/agent/sessions/<UTC timestamp>_<suffix>/`. They hold CEII-derived material and must be
treated as CEII:

- `context.json` (project root, selected run IDs, model, endpoint, runtime, route);
- `prompts/<nanoseconds>.txt`, the exact prompt text handed to the CLI;
- `transcript.jsonl`, including the user's questions verbatim and the model's answers;
- `runtime_events.jsonl`, the normalized runtime event stream plus captured diagnostics;
- `tool_calls.jsonl`, the append-only tool audit, which contains grid loading values and facility keys;
- `usage.json` and `status.json`;
- `generated/*.py` and `generated/*.json`, proposed scripts and their review records;
- `generated/executions/*/script.py`, `result.json`, and `output.txt`, the approved bytes and the sandbox output;
- `script_executions.jsonl`.

Directories are mode `0700` and files are mode `0600`. Session folders inherit the project's encryption, backup,
retention, and deletion rules. Nothing leaves the project folder unless the user explicitly chooses
**Export session audit**; that archive is an unencrypted ZIP written `0600`, is a sensitive artifact, and must be
handled as CEII. Sessions persist until an operator deletes the session folder, and are covered by the same approved
deletion procedure as run folders. Note that project-level `exports/` is outside the session and outside the mounted
run folder.

### Egress Audit Scope

The audit answers "what did GridLens hand to the runtime, and what did the runtime hand back", not "what bytes
crossed the socket". It records the logical prompts, the tool schemas GridLens exposes, every tool call with its
arguments and its bounded result, the runtime's event stream, and the generated scripts and sandbox output. It cannot
record fields the provider CLI adds on its own, transport headers, retries or internal re-prompts inside the CLI,
tokenization, or the exact network bytes. Treat the audit as authoritative for GridLens-controlled content and as
incomplete for the wire. If byte-level egress evidence is required, capture it at the host or network layer.

### Generated Scripts

Generated code is saved for review and is never executed without per-script approval bound to the reviewed SHA-256
hash. The reviewed bytes are snapshotted, so a later edit to the proposal cannot change what runs.

Execution uses a separately prepared image identified by its immutable `sha256` image ID and carrying the
`org.gridlens.purpose=generated-analysis` label, with `--pull=never`, `--network none`, `--read-only`,
`--cap-drop ALL`, `no-new-privileges`, the invoking non-root UID/GID, and CPU, memory, pids, nofile, fsize, and
CPU-time limits. GPUs are hidden with `NVIDIA_VISIBLE_DEVICES=void`. Writes are confined to `noexec` tmpfs mounts.
Only two paths are bind-mounted, both read-only: the selected run folder at `/run-data` and the reviewed script.
The only egress is stdout, capped at 256 KiB, and its output is recorded as untrusted.

The whole run folder is mounted, rather than just `work/`, as a distinct reviewed case. Questions the feature exists
to answer ("How did you run the contingency analysis?", "Where are my files?") need `logs/`, `manifest.json`, and
`status.json`, and the deterministic tools already expose those files to the model, so a narrower mount would break
the documented script contract without removing a data class the agent can otherwise reach. The mount is read-only
and the container has no network, so the sandbox adds no write path and no egress path to the run folder.

The [Docker Group Risk](#docker-group-risk) section applies to this container unchanged.

### Hosted Inference

Hosted runtimes (Codex, Claude Code) are prohibited. Their adapters ship disabled and must stay disabled.

`GRIDLENS_ALLOW_HOSTED_AGENT` is deliberately an operator action in the environment rather than a GUI preference, so
that an ordinary feature change cannot relax the local-only rule by accident. Setting it is not an authorization.
Authorization is a written governance decision, recorded in this file and in `CONTRIBUTING.md` before the variable is
ever set, and it must define at minimum:

1. which data classes may leave the machine, and which may not;
2. the approved providers, accounts, and contractual terms covering them;
3. provider-side retention, training use, and deletion commitments;
4. data residency and any cross-border constraints;
5. incident response, including who is notified and within what window when CEII reaches an unapproved destination;
6. which administrators may set the variable, and how that is enforced and reviewed on deployed machines.

Until such a decision exists, treat any machine with `GRIDLENS_ALLOW_HOSTED_AGENT` set as misconfigured.

## Operational Controls

Use these controls for regulated deployments:

1. Pull or load Docker images before CEII inputs are opened.
2. Prepare and pin the generated-analysis sandbox image before CEII inputs are opened. GridLens never pulls it.
3. Pin production image versions. Do not use `latest`.
4. Keep image tarballs and installers in an approved internal repository.
5. Disable automatic updates unless approved.
6. Store project folders on encrypted local storage.
7. Back up project folders through approved internal systems only.
8. Restrict Docker group membership to approved users.
9. Review any extra Docker arguments before use.
10. Leave `GRIDLENS_ALLOW_HOSTED_AGENT` unset, and audit for it.

## Docker Group Risk

Membership in the `docker` group gives a user root-equivalent control of the host through Docker. This is a Docker platform property, not an app-specific choice. For CEII environments, get written approval from the security owner before relying on Docker group access.

## Future Hardening

Production hardening should add:

- signed installers;
- signed container images;
- SBOM generation;
- pinned Python dependency hashes;
- a local-only update mechanism;
- explicit run and agent-session retention and deletion policies;
- parser validation against known GridPACK output schemas.
