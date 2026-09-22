# Implementation Plan: AI-Assisted Transmission Planning Agent

Status: delivered for the Hermes and Ollama local runtime, and validated end to end on 2026-09-21.
Hosted runtimes stay disabled behind the §7 governance gate. The Agent tab GUI is partly built; see
`handoff.md` for what is open and `agent_findings.md` for the verified defect list.

Initial validation target: DGX Spark, DGX OS 7 / Ubuntu 24.04.5 LTS, aarch64

Initial runtime: Hermes Agent with local Ollama models

Later runtimes: Codex CLI and Claude Code, subject to the security gate in §7

## 1. Review outcome

The feature is feasible, but the previous plan should not be implemented as written.

| Finding | Required correction |
|---|---|
| The plan called Hermes the only v1 runtime, although the requested UI includes Hermes, Codex, and Claude Code. | Define one runtime-adapter contract. Deliver Hermes first; add Codex and Claude adapters without changing the tool layer. |
| It claimed the MCP server could enforce all egress. | The runtime adapter sends the user prompt before MCP is involved. Gate remote sessions before process launch and pass all GridLens-controlled outbound content through one policy layer. |
| It proposed project-wide discovery from the model. | Bind each agent session to the project and run IDs selected in the GUI. Tools must not accept arbitrary filesystem paths or enumerate unrelated projects. |
| It said existing analysis helpers were in `analysis/`. | `max_line_utilization_rows` and the area/voltage summaries are currently in `gui/analysis_view_models.py`. Move domain logic into `analysis/` before exposing it as tools; leave GUI adapters thin. |
| It assumed an existing shared analysis job queue. | `gui/analysis_tab.py` creates a new one-worker `ProcessPoolExecutor` for each build. Introduce a reusable analysis service or serialize agent builds explicitly; do not claim an existing queue. |
| It assumed current Parquet conversion gives cheap contingency predicate pushdown. | `convert_csv_to_parquet` writes unpartitioned Dask parts or one eager cuDF file. Benchmark it. Add a compact contingency summary and an event-indexed layout before promising fast drill-down. |
| It used “extra capacity” as though unused line rating were transfer capability. | Report thermal loading margin only. Transfer capability requires a defined transfer study and cannot be inferred from `100 - utilization_pct`. |
| It proposed a hand-written MCP implementation. | Use the official MCP Python SDK and pin the tested release. Protocol and transport code are not a useful project-specific asset. |
| It claimed exact remote egress accounting through opaque vendor CLIs. | Audit the logical prompts, tool results, and attachments GridLens supplies. Do not claim to capture vendor-added fields or exact network bytes. |
| It put generated-code execution in the core design. | Exclude it from the initial release. Add it only after deterministic tool coverage, audit behavior, and the sandbox image are independently accepted. |

Recommendation: ship a read-only, loopback-only Hermes/Ollama vertical slice first. Preserve the provider seam from the start, but do not enable hosted inference until the repository's CEII policy is formally changed.

## 2. Scope

### Initial release

- Add an **Agent** tab.
- Detect Hermes, its effective model endpoint, Ollama availability, and installed Ollama models.
- Let the user choose among locally installed models; do not install a CLI or model.
- Answer questions about the selected project and selected completed run(s).
- Use bounded deterministic tools for file location, run provenance, convergence, utilization, violations, and comparison.
- Show tool activity and source provenance.
- Save an auditable session record under the project.
- Treat project data and tool output as untrusted input to the model.

### Designed now, delivered later

- Codex CLI and Claude Code adapters.
- Hosted inference, only after the §7 governance gate.
- Full per-contingency branch drill-down over an indexed large-data artifact.
- Generated analysis scripts and sandboxed execution.
- Launching GridPACK runs or changing a project/run.

### Non-goals

- GridLens does not ship inference, model weights, provider credentials, or a CLI installer.
- The agent is not a source of numerical truth. Deterministic GridLens functions are.
- The initial agent does not modify input files, run folders, settings, or GridPACK configurations.
- No model-specific prompt, schema, or code path is permitted in the tool layer.

## 3. Verified baseline

### Repository and sample data

The following statements were checked against this repository and the supplied sample run.

- The sample flat result is `8,697,686,858` bytes.
- `reports/interactive_tables/pflow_mm.csv` is `1,919,943` bytes with 8,646 facility rows.
- `branch_metadata.csv` is `2,010,014` bytes with 8,646 facility rows; `area_metadata.csv` has 8 rows.
- The interactive manifest records dataset/parser version `2026.07.05` and the cuDF backend.
- `pflow_mm.csv` contains base, mean, maximum utilization, binding contingency, contingency count, overload count, bus, area, voltage, and facility metadata. This is sufficient for most first-release questions without reopening the 8.7 GB CSV.
- The flat file has the fields needed for later drill-down: contingency/event, branch key, MW/Mvar/MVA, rating, loading, violation, voltage, and angle.
- `analysis/interactive.py` already validates cache freshness and falls back to a cold analysis build.
- `analysis/csv_flat.py` can create Parquet, but the current output is not organized by contingency/event.
- `analysis/summary.py` exports the selected run directory only. Project-level agent sessions require a separate, explicit export option.
- `CONTRIBUTING.md` currently forbids sending inputs, outputs, manifests, or derived exports to online services. This blocks hosted providers today.

### Local runtime baseline observed on 2026-09-21

These versions are a development baseline, not hardcoded application defaults.

| Runtime | Observed version/state | Useful probe or interface |
|---|---|---|
| Hermes Agent | `0.21.4`; model endpoint `http://127.0.0.1:11434/v1` | `hermes --version`, `hermes config get model`, profiles, MCP, structured one-shot chat |
| Ollama | client `0.34.2`; service reachable on loopback | `GET /api/tags` |
| Local models | Enumerated from `/api/tags` at probe time. On 2026-09-21 that was `gpt-oss:120b`, `granite4.2:30b`, `gemma4:31b`, `nemotron-3-super:120b`, `nemotron3:33b`, `qwen3.6:35b` | `agent/hermes.py` lists only models that advertise the `tools` capability |
| Codex CLI | `0.155.1`; authenticated | `codex login status`, `codex exec --json` |
| Claude Code | `2.1.278`; authenticated | `claude auth status --json`, `claude -p --output-format stream-json` |

Relevant current documentation:

- [Hermes CLI and structured output](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/cli-commands.md)
- [Hermes toolsets and MCP server toolsets](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/toolsets-reference.md)
- [Hermes profiles](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/profile-commands.md)
- [Ollama model inventory API](https://docs.ollama.com/api/tags)
- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Codex CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-usage)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

CLI behavior is versioned external behavior. Each adapter must record the detected version and reject unsupported versions with a diagnostic; it must not silently guess new output formats.

## 4. Architecture

```text
AgentTab (PySide6)
    |
AgentController / worker thread
    |
RuntimeAdapter -----------------------------------+
    |                                              |
    +-- HermesAdapter  (first release)             |
    +-- CodexAdapter   (later)                     | structured events
    +-- ClaudeAdapter  (later)                     |
                                                   v
                                   session event normalizer
                                                   |
                                      transcript / activity UI

Runtime launches only the GridLens MCP server
    |
official MCP Python SDK, stdio
    |
ToolService -> analysis/core functions -> selected run artifacts
    |
append-only tool audit + provenance
```

### 4.1 Session capability boundary

When the user sends the first message, GridLens writes an immutable session context containing:

- canonical project root;
- allowlisted run directory or directories;
- provider, model, and local/remote classification;
- output limits and timeouts;
- paths to the audit files;
- a random session identifier.

The context path is passed in the runtime subprocess environment and inherited by the MCP child. The server validates the file before serving any tool.

Tools receive logical run IDs, never absolute paths. Resolution must reject:

- a run outside the selected project's `runs/` directory;
- a run not selected for this session;
- `..`, absolute paths, symlinks escaping the allowlisted root, and non-regular source files;
- a project root different from the one loaded in the GUI.

Changing provider, model, project, or run selection starts a new session. This prevents stale context and removes the need for a mutable global “current session” pointer.

### 4.2 Runtime adapter contract

```python
class RuntimeAdapter(Protocol):
    def probe(self) -> RuntimeStatus: ...
    def prepare(self, session: SessionContext) -> PreparedRuntime: ...
    def start_turn(self, prepared: PreparedRuntime, prompt_path: Path) -> RunningTurn: ...
    def parse_event(self, line: str) -> RuntimeEvent: ...
    def cancel(self, turn: RunningTurn) -> None: ...
```

`RuntimeEvent` normalizes session/thread ID, text delta, tool start/result, usage, completion, and error. The GUI and session store must not parse provider-specific output.

`AgentController` owns the canonical conversation record. An adapter may keep a live structured-input process or use the runtime's continuation ID, but vendor session state is never the only copy. Multi-turn and cancellation behavior are acceptance-tested per adapter; if a CLI cannot resume safely without copying project data into its own unmanaged history, use a bounded transcript replay or do not enable that adapter.

All subprocesses use argument lists, `shell=False`, a minimal environment, a new process group, bounded stdout/stderr capture, a wall-clock timeout, and group termination on Stop or application exit. Prompts are written to a session file or supplied over stdin; do not interpolate them into a shell command.

### 4.3 Provider-specific requirements

#### Hermes + Ollama

- Use a dedicated `gridlens` profile created with no bundled skills.
- The profile contains only the GridLens MCP server and the chosen local model/provider configuration.
- Invoke structured non-interactive chat (`hermes chat ... --format stream-json`) rather than `hermes -z`, so the adapter receives session, tool, usage, and result events.
- Restrict toolsets to the dynamic GridLens MCP toolset and use `--ignore-rules` in an empty session scratch directory.
- Verify the effective model endpoint before every session. Under `loopback_only`, every resolved address must be loopback and proxy variables must not redirect local inference.
- Query `/api/tags` only for a verified Ollama endpoint. Model names come from the endpoint, not source code.
- Do not consider the adapter ready until an integration test proves that a one-shot prompt can discover and call the MCP server and that no built-in Hermes tool is exposed.

GridLens may offer to create or repair the dedicated profile after showing the exact commands and receiving confirmation. It must never alter the user's default Hermes profile.

#### Codex CLI

- Probe installation/version and `codex login status` without reading credential files.
- Consume `codex exec --json`; use ephemeral, read-only, non-interactive execution in a scratch directory.
- Ignore user configuration and rules. Supply only the GridLens MCP configuration for the session.
- Treat Codex as remote unless a future adapter explicitly implements and verifies Codex's local `--oss` mode.
- Before enablement, prove that the effective configuration exposes only GridLens MCP tools and no shell, web, file, plugin, hook, or unrelated MCP capability. If current CLI configuration cannot establish that boundary, do not ship the adapter; evaluate `codex app-server` as the supported deep-integration alternative.

#### Claude Code

- Probe installation/version and `claude auth status --json` without logging account details.
- Prefer a verified bidirectional print-mode stream (`--input-format stream-json --output-format stream-json`) so multi-turn state can remain in the GridLens-controlled process; consume structured output only.
- Use restricted mode, no session persistence, no permission prompts, a session-only MCP config, and strict MCP config isolation.
- Run in an empty scratch directory and allow only the GridLens MCP tool names.
- Treat Claude Code as remote.
- Before enablement, prove with the installed CLI that hooks, skills, browser/web, shell/code execution, filesystem access outside scratch, plugins, and unrelated MCP servers are unavailable.

Do not copy a nominal set of “safe flags” between runtimes. Each adapter has its own executable integration test and compatibility record.

### 4.4 MCP server

Use the official MCP Python SDK over stdio. Add it as a pinned runtime dependency after a PyInstaller spike. Do not implement JSON-RPC framing, initialization, cancellation, or schema negotiation locally.

The frozen `GridLens` executable dispatches `--mcp-server` before importing Qt. Tests must cover the source entry point and the PyInstaller entry point.

The MCP server is read-only in the initial release. It writes only append-only audit events to its session directory. A tool-call record contains:

- call ID, tool name, validated arguments, start/end time, and outcome;
- returned and total row counts plus truncation status;
- dataset/parser version and metric-definition version;
- source paths relative to the project, sizes, mtimes, and available recorded hashes;
- error code and remedy.

Do not hash the 8.7 GB flat file on every call. Reuse recorded hashes where available and record file identity/mtime/size for derived files.

### 4.5 Tool result contract

```json
{
  "data": {"rows": [], "returned": 0, "total_matching": 0, "truncated": false},
  "provenance": {
    "sources": [],
    "dataset_version": "...",
    "parser_version": "...",
    "metric_definition_version": "..."
  },
  "warnings": [],
  "error": null
}
```

Requirements:

- JSON Schema generated from typed inputs by the MCP SDK.
- Server-side row and byte caps that cannot be raised by the model.
- Deterministic sort order and explicit units.
- Stable error codes; no raw traceback or secret-bearing environment data returned to the model.
- Relative source identifiers in remote sessions. Absolute local paths may be shown by the GUI, not sent to a hosted model.
- No arbitrary file-read, SQL, Python, shell, or generic “query” tool.
- Each final answer cites tool-call IDs such as `[T3]`. The GUI resolves only IDs present in `tool_calls.jsonl`; invented IDs render as invalid rather than as sources.

## 5. Deterministic analysis tools

Keep the first catalog small. Tool descriptions should encode when a tool is not scientifically sufficient.

| Tool | Initial behavior |
|---|---|
| `get_run_inventory` | Selected runs, status, timestamps, available caches and outputs. |
| `locate_run_artifacts` | Resolve a controlled enum such as `raw_input`, `flat_results`, `configuration`, `run_log`, `interactive_tables`, or `exports`. |
| `get_run_method` | Manifest and section-scoped parsed XML values: image, executable, MPI count, exact recorded command, contingency rating, voltage limits, control settings, input hashes, and analysis backend. |
| `summarize_convergence` | Counts and bounded examples from the 719 KB convergence file. |
| `rank_branch_loading` | Rank selected facility types by base or maximum N-1 utilization, with binding contingency and filters. |
| `summarize_loading` | Area or voltage-class summary using the same facility and voltage filters as the GUI. |
| `list_thermal_violations` | Facilities exceeding a specified loading threshold, bounded and sorted. |
| `get_branch_loading` | Base, mean, maximum, overload count, rating metadata, and binding contingency for one canonical branch key. |
| `search_buses` | Bounded exact/prefix/fuzzy lookup against cached bus metadata. |
| `compare_runs` | Branch-key-aligned loading deltas for two explicitly selected runs; report unmatched facilities. |
| `rank_contingencies` | Add only after the compact contingency-summary artifact in §6 exists. |

### Metric definitions

- “Most congested” defaults to highest `max_utilization_pct` across converged contingencies, and the answer must state that definition.
- Also expose base utilization and overload count so a single worst case is not presented as persistent congestion.
- “Thermal margin” is `100 - max_utilization_pct` percentage points for a named rating basis. Negative values are overloads.
- Do not call thermal margin “available transfer capability,” “extra generation capacity,” or “load-serving capacity.” Those require a specified transfer, dispatch assumptions, and another power-flow/contingency study.
- Preserve the full canonical branch key: from bus, to bus, circuit/line ID, and section. Do not merge parallel circuits.
- Separate non-transformer branches, two-winding transformers, three-winding transformer branches, and equivalents using the repository's existing classifications.
- Results based on failed/non-converged contingencies must carry an explicit warning and denominator.

Move reusable calculation code from `gui/analysis_view_models.py` into `analysis/` with regression tests. Both the GUI charts and tools then call the same pure functions.

## 6. Data-access plan

| Tier | Artifact | Use |
|---|---|---|
| 0 | `project.json`, `manifest.json`, `status.json`, `input.xml`, bounded log excerpts | Orientation and method questions |
| 1 | Existing `reports/interactive_tables/*.csv` | Loading, thermal margin, violations, grouping, branch lookup |
| 1A | Convergence CSV | Convergence and failure summaries |
| 2 | New compact `contingency_summary` table | Rank contingencies without reading the flat dataset per question |
| 3 | New event-indexed Parquet layout | One-contingency or one-branch drill-down after benchmarking |

The cache builder should produce `contingency_summary` during the same pass that aggregates the flat CSV. At minimum it contains event/contingency ID, convergence state, monitored-facility count, violation count, maximum loading, and the worst facility key. This is thousands of rows rather than tens of millions.

Do not declare the existing Parquet output suitable for random drill-down. First benchmark:

1. current unpartitioned output;
2. Parquet sorted by event with useful row-group statistics; and
3. a bounded event-bucket partitioning scheme.

Avoid one partition per contingency; thousands of small directories/files are a separate scalability failure. Record conversion time, disk amplification, cold and warm query latency, peak host memory, and peak GPU memory on the supplied run before selecting a layout.

Measured on 2026-09-21, on the supplied run: an 8,697,686,858-byte flat CSV yielding 74,701,440 indexed rows,
through PyArrow on the CPU, with no GPU memory used by any layout.

| Layout | Build | Parquet bytes | Disk ratio | Event query, cold and warm | Branch query | Peak host RSS |
|---|---|---|---|---|---|---|
| Buckets | 101.5 s | 3,126,265,202 | 0.359 | 0.069 s / 0.058 s | 2.07 s | 2.02 GB |
| Sorted | 130.3 s | 2,532,316,449 | 0.291 | 0.127 s / 0.102 s | 2.75 s | 4.06 GB |
| Unpartitioned | 105.5 s | 2,532,590,577 | 0.291 | 0.170 s / 0.162 s | 5.49 s | 4.09 GB |

Selected layout: 64 event buckets. It builds fastest, answers an event query roughly 2.5 times faster and a
branch query roughly 2.7 times faster than the unpartitioned layout, and peaks at half the host memory, for
about 24% more disk. The reads were first and warm reads without a forced cache flush, so treat the cold
figure as a first read rather than a cold-cache measurement. `scripts/benchmark_agent_index.py` reproduces
the table.

Cache builds are explicit user-visible jobs. Introduce a non-GUI `AnalysisService` that owns serialization, cancellation, and progress. The Analysis tab and Agent tab both use it. Until that service exists, the agent must return `ANALYSIS_NOT_BUILT` rather than starting an untracked multi-minute build.

## 7. Security and data governance

### 7.1 Local versus remote

Classify the effective inference route, not the brand name.

- Hermes is local only when its effective base URL resolves exclusively to loopback and the selected provider is the expected local service.
- Codex CLI and Claude Code are remote for the planned adapters.
- A runtime that cannot prove its route fails closed under `loopback_only`.

The preflight decision occurs before any user text, project name, path, tool schema containing project data, or tool result is passed to the runtime.

### 7.2 Current policy gate

Hosted inference conflicts with `CONTRIBUTING.md`. Therefore:

- hosted providers appear as disabled with a plain explanation in development builds;
- enabling them requires a separate, reviewed governance change to `CONTRIBUTING.md` and `docs/security_ceii.md`;
- the change must define authorized data classes, approved providers/accounts, retention, residency, incident response, and administrator controls;
- a normal feature PR must not silently weaken the current local-only rule.

Pseudonymization is not an initial mitigation. Grid topology, ratings, voltage classes, and loading patterns may remain identifiable, and reliable de-pseudonymization of free-form model output is not guaranteed. Reconsider it only through a separate threat model.

### 7.3 Egress audit

For an approved remote session, record the canonical logical content controlled by GridLens:

- user messages after any approved transformation;
- tool schemas exposed;
- tool results returned;
- files or images attached;
- provider/runtime/model/version and timestamps.

Store these as sensitive project artifacts with an explicit retention policy. State plainly that the record does not include provider-added system fields, transport headers, retries, or exact encrypted network bytes.

### 7.4 Prompt injection and tool isolation

- Treat logs, filenames, RAW labels, contingency names, cached tables, and generated script output as data, never instructions.
- Delimit untrusted strings and cap every textual excerpt.
- Disable all runtime-native tools not required for GridLens.
- Never put the project root in the runtime working directory or expose it through a file tool.
- Escape model output before rendering it in `QTextBrowser`; do not allow arbitrary HTML or external-resource loading.
- Credentials remain owned by each CLI. GridLens runs status probes but never reads, copies, or records tokens.

## 8. Session artifacts and GUI

```text
<project>/agent/sessions/<UTC timestamp>_<random suffix>/
  context.json          immutable selected project/run capability
  manifest.json         runtime, version, provider, model, route, command template
  transcript.jsonl      user and assistant messages
  runtime_events.jsonl  normalized structured CLI events
  tool_calls.jsonl      canonical MCP audit and provenance
  usage.json            normalized usage when the runtime reports it
  status.json           running | completed | cancelled | failed
  generated/            absent in the initial release
```

Do not store credentials or raw process environments. Redact command arguments that may contain secrets. Session export is opt-in and separate from the current run ZIP.

The Agent tab contains:

1. runtime/model selector and a Local/Remote route badge;
2. installation, authentication, endpoint, MCP, and isolation diagnostics;
3. selected project/run context; changing it starts a new session;
4. transcript with escaped text;
5. normalized live activity from structured CLI events;
6. Sources panel from MCP provenance;
7. input, Send, Stop, and Open Session Folder controls.

When a CLI is absent or unauthenticated, show a vendor documentation link and copyable commands. GridLens does not run installers or login flows. For local Ollama, “authenticated” is not applicable; check endpoint health and the selected model instead.

## 9. Generated code extension

This is not part of the initial release. Add it only if evaluation shows important, valid questions that cannot be covered by deterministic tools.

The model may propose a script, but GridLens first saves it for review. Execution requires per-script user approval and a separate pinned analysis image, not the GridPACK solver image. The container must use:

- no network, no GPU, read-only run mount, and one bounded output mount;
- non-root UID/GID, dropped capabilities, `no-new-privileges`, a read-only root filesystem, and a tmpfs;
- CPU, memory, process-count, file-size, output-size, and wall-clock limits;
- no Docker socket, home directory, SSH agent, provider credentials, or host environment secrets.

Capture the script, purpose, approval, image digest, command, stdout/stderr excerpt, exit code, and output hashes. Generated results are untrusted until a deterministic validator or user accepts them. Docker group membership remains a root-equivalent host risk; container flags do not remove that platform risk.

## 10. Delivery sequence and exit criteria

### Phase 0: semantics and governance

State: Delivered. Metric definitions are implemented in `agent/tools.py`, hosted providers stay disabled, and session retention is documented in `docs/security_ceii.md`.

- Approve the metric definitions in §5.
- Decide whether hosted providers are permitted in this deployment. Keep them disabled if no written decision exists.
- Define session retention/export policy.

Exit: reviewed decision record; no source changes that weaken current CEII rules.

### Phase 1: model-free tool service

State: Delivered. Fifteen tools, the result envelope, the audit, the developer CLI, and the compact contingency summary all exist and are tested without a model.

- Move reusable utilization logic into `analysis/`.
- Implement session scoping, result envelopes, provenance, Tier 0/1/1A tools, and a developer CLI.
- Add the compact contingency summary to the analysis pipeline.

Exit: golden fixture tests pass without a model or MCP process; tools cannot address an unselected run.

### Phase 2: MCP and packaging

State: Delivered and verified. `mcp==1.30.0` is pinned, `--mcp-server` dispatches before Qt, and the official SDK conformance test passes against source, the final frozen executable, and the executable extracted from the arm64 Debian package. The package includes the sandbox recipe under `/usr/share/doc/gridlens/agent-sandbox/`.

- Add the official MCP SDK and stdio server.
- Add `--mcp-server` dispatch before Qt imports.
- Add append-only auditing and an official-SDK client conformance test.
- Verify the frozen executable and Debian package.

Exit: source and packaged MCP entry points pass the same tests; stdout contains protocol messages only.

### Phase 3: Hermes and Ollama vertical slice

State: Delivered and validated. See the exit note below.

- Implement probe, isolated profile preparation, structured event parsing, cancellation, and loopback enforcement.
- Run the same evaluation set against every installed model that advertises tool support.

Exit: every model uses the same prompt and tools, no model name appears in the analysis or tool code, and no
non-GridLens tool is exposed. Met on 2026-09-21. All six installed models answered correctly through the real
Hermes CLI: qwen3.6:35b in 20.6 s, nemotron3:33b in 25.6 s, gemma4:31b in 53.8 s, gpt-oss:120b in 55.0 s,
granite4.2:30b in 71.1 s, and nemotron-3-super:120b in 72.6 s. A separate test drives the installed CLI against
a synthetic loopback model server and asserts that only the fifteen GridLens tools are exposed.

Future scored local evaluations target `nemotron3:33b` and `gemma4:31b` using the same synthetic questions
and tool catalog. The earlier six-model result above is retained as a historical compatibility check.

### Phase 4: GUI

State: Delivered. The registry-driven provider selector, install and sign-in guidance, route badge, streamed text, activity view, Sources panel, session browser, and shared `AnalysisService` exist. Hosted sessions remain behind the governance gate.

- Add the Agent tab, worker/controller, activity, Sources panel, diagnostics, and session browser.
- Share `AnalysisService` with the Analysis tab.

Exit: responsive start/stop, no GUI-thread blocking, safe rendering, clean shutdown, and an end-to-end local answer with citations.

### Phase 5: Codex and Claude adapters

State: Adapters written, shipping blocked. Claude Code isolation was proven against the installed CLI. Codex isolation could not be proven in 0.155.1, so that adapter is probe-only and fails closed.

- Implement adapters independently against the verified CLI versions and structured streams.
- Add opt-in installed-CLI tests for authentication probes, MCP discovery, tool isolation, cancellation, failure handling, and version drift.

Exit: adapters satisfy the same contract and isolation suite. Shipping remains blocked unless Phase 0 authorized hosted inference and the security documents were changed separately.

### Phase 6: large-data drill-down and generated code

State: Delivered. The layout was selected from measurement, and the generated-script review and sandbox path exists.

- Select the indexed Parquet layout from measured results.
- Add bounded contingency/branch drill-down.
- Only if justified, add the generated-script review and sandbox path.

Exit: a performance report on the supplied run, resource-limit tests, and a security review. The report is in §6.

## 11. Verification

Automated tests:

- schema generation, byte/row caps, deterministic ordering, units, and stable errors;
- path traversal, symlink escape, unselected-run, malformed manifest, and stale-cache cases;
- metric semantics for parallel circuits, transformers, failed contingencies, missing ratings, and unmatched comparison rows;
- MCP lifecycle/conformance through the official client;
- exact adapter argv/environment construction and structured-event parsing;
- malicious prompt-like strings in logs, labels, and tool output;
- runtime isolation: no built-in or unrelated MCP tool visible;
- Stop/timeout kills the full process tree;
- PyInstaller/Debian entry-point behavior;
- offscreen Qt view-model and controller tests.

Model evaluation uses synthetic or approved data with known answers. Score at least:

- correct tool and arguments;
- numerical fidelity to deterministic output;
- unit and metric-definition fidelity;
- citation/provenance completeness;
- explicit handling of truncation, missing data, and non-convergence;
- refusal to invent a result when a tool fails;
- absence of cross-project access.

Performance validation on the supplied run records cold/warm latency and peak resources. Set release thresholds from those measurements; do not invent them in advance.

Repository verification remains:

```bash
python -m pytest
python -m compileall -q src tests
git diff --check
```

## 12. Source layout as delivered

```text
src/gridlens/agent/
  runtime.py          provider-neutral status, events, and the adapter protocol
  providers.py        the provider registry: hermes, claude, codex
  process.py          shared subprocess, environment, and MCP child helpers
  prompt.py           the one system prompt every runtime sends, and turn composition
  policy.py           loopback route enforcement, Ollama probes, hosted-provider gate
  session.py          the immutable session capability, audit append, export
  controller.py       the turn loop, event normalization, citation normalization
  hermes.py           the Hermes adapter, validated
  claude_code.py      the Claude Code adapter, disabled by policy
  codex.py            the Codex adapter, probe only and fail closed
  tools.py            the fifteen deterministic tools and the result envelope
  mcp_server.py       the official SDK stdio server and the developer tool CLI
  scripts.py          generated-script proposals and the approved-script sandbox
src/gridlens/analysis/
  service.py          AnalysisService, shared by the Analysis and Agent tabs
  contingencies.py    the compact contingency_summary table
  event_index.py      the bucketed Parquet index and its bounded queries
  loading.py          utilization calculations shared by the GUI and the tools
src/gridlens/gui/
  agent_tab.py        the Agent tab
  agent_jobs.py       the QThread wrapper around AnalysisService
  script_review.py    the approve-and-run dialog
packaging/agent/
  Dockerfile          the sandbox image recipe
  README.md           how to build and pin it
```

This differs from what §4 through §11 predicted, and the flat modules are the delivered shape. The predicted
`providers/` and `tools/` subpackages were not created. Three adapters live beside each other as
`hermes.py`, `claude_code.py`, and `codex.py`, with `providers.py` as the registry, and the tool service
stayed one cohesive `tools.py` rather than six modules. `gui/agent_view_models.py` was not needed, because
the view logic is small enough to sit in the tab alongside `agent_jobs.py` and `script_review.py`. Three
modules the plan did not predict do exist: `process.py`, `prompt.py`, and `providers.py`, which together are
what keeps the feature model-agnostic.

Also modified: `main.py`, `main_window.py`, the analysis modules that own the shared calculations and caches,
the packaging metadata, and focused tests. Update the architecture, user, packaging, and security
documentation only for behavior that is actually approved and delivered.
