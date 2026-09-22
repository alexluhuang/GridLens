# Handoff: AI-assisted transmission planning agent

Written 2026-09-21; revised 2026-09-22 after the work was merged to `main` and the remediation batch
failed. The status here is current as of the revision.

This document is written for whoever picks the feature up next, human or agent. It records what exists,
what was measured, what is still open, and the traps that cost time. Read §1, §5 and §6 first, then the
defect register in `docs/plans/agent_findings.md`, which is the actual work list.

---

## 1. Where the work lives

Everything is on **`main`**, and `main` is in sync with `origin/main`. The isolated worktree this work was
built in has been removed; its branch no longer exists. There is nothing to recover and nothing to merge.

The history reads, oldest first:

| Commit | What it is |
|---|---|
| `0bef2f9` … `d4f53c0` | The previous agent's committed work (§3). |
| `9fac226` | A verbatim checkpoint of the previous agent's uncommitted working tree, carried forward so it could be reviewed on its own. |
| `40888db` | Merge of `feat/hermes-planning-agent` into `main`. |
| `629d799` | Snapshot of the worktree: the provider seam (§4.2) plus the seven findings that the remediation agents managed to write before they were killed (§5). |
| `754d71c` | Ignore local Claude worktrees. |
| `2a7a2e9` | Repairs a broken test module and makes the developer CLI report stable error codes (§5). |
| `76954de` | `docs/plans/agent_findings.md`, the verified defect register. |

Two working documents sit next to this one:

- **`docs/plans/ai_planning_agent.md`**: the implementation plan. It no longer says it is a proposal; finding 9 is closed.
- **`docs/plans/agent_findings.md`**: all 34 verified defects with their corrected fixes and current
  status. **This is the work list.** It was copied out of session scratch before that scratch was
  discarded, so it is the only surviving copy.

The reference project used for every measurement in this document is
`/home/alh360/GridLensProjects/GridPACK_Test_Project`, run `2026-07-28_14-46-26`.

---

## 2. What the feature is

A new **Agent** tab in GridLens. The planner types a natural-language question ("where are the most
congested lines?", "how did you run the contingency analysis?", "where are my files?"). A model answers,
but every fact comes from deterministic GridLens functions exposed to it as tools over a GridLens MCP
server, so the model never handles the 8.7 GB flat result itself and is never the source of numerical
truth. When no tool fits, the model may *propose* Python, which is saved under the project for the user to
review and optionally run in a locked-down container.

GridLens ships no inference, no model weights, and no credentials, and never installs a CLI or signs anyone
in. It detects what the user installed, and tells them what to install or which login command to run.

Design authority, in order: the user's own description of the feature, then `docs/plans/ai_planning_agent.md`.


### 2.1 Requirement by requirement, against what the user actually asked for

This is the comparison that matters. "Backend" means the layer below the GUI is complete and tested; only
the tab needs wiring.

| The user's requirement | Status | Where it stands |
|---|---|---|
| A new tab in GridLens | **done** | `AgentTab` is registered in `gui/main_window.py` and receives project and run-selection signals. |
| On launching the tab, check whether the model/CLI is installed | **done** | The tab probes on first show; each adapter reports installation and its validated version. |
| Check the user is logged in with their own credentials | **backend done, GUI open** | `RuntimeStatus.authenticated` is three-valued, so "not applicable" (local Ollama) is distinct from "not signed in". Both hosted adapters read only the boolean from the vendor's own status command and never touch a credential file. The tab does not render it yet, per findings 19 and 20. |
| If not, prompt the user to install the CLI and log in | **backend done, GUI open** | `install_command`, `login_command` and `docs_url` are populated per provider. Nothing displays them yet; this is item 3 of §6.1. |
| Select a local provider (Hermes Agent with Nemotron) | **done** | Validated end to end against six installed Ollama models, Nemotron among them. |
| Select an online model (Codex or Claude Code) | **partial, by policy** | The Claude Code adapter is complete and its tool isolation was proven against the installed CLI. The CEII gate switches it off, not missing code. Codex cannot be isolated in 0.155.1, so it ships probe-only and fails closed with the reason recorded. The tab still lists both as hardcoded disabled strings rather than registry entries, per §6.1. |
| GridLens provides no inference and installs nothing | **done** | No model, no weights, no credentials, no installer anywhere in the tree; every "how do I get this" path is a documentation link plus a command the user runs. |
| Natural-language question in, natural-language answer out | **done** | Validated on all six local models with the identical prompt and tool set. |
| The agent runs all required analyses | **done, with one deliberate limit** | The agent reads any cached artifact it needs, but it cannot *start* a multi-minute cache build; it returns `ANALYSIS_NOT_BUILT` and the user presses Build / refresh analysis. That is the plan's rule (§6) so a question cannot silently launch a long untracked job. Worth confirming the user still wants it that way. |
| Deterministic GridLens functions the agent calls as tools | **done** | Fifteen tools with a uniform result envelope, server-side caps, provenance, and an append-only audit. |
| So the agent never manipulates the large files itself | **done and measured** | Questions are answered from a ~1.9 MB cache and a bucketed Parquet index; an event query over the 8.7 GB run's 74.7 M rows returns in 0.07 s. |
| If no function fits, the agent generates code saved under the project for auditing | **done** | `propose_analysis_script` only ever saves, hashed and AST-checked, under `<project>/agent/sessions/<id>/generated/`. Running it needs the user to approve that exact hash in a review dialog, and it runs in a no-network, read-only, resource-capped container. |
| Model-agnostic, while being built and tested on the local agent | **done** | One adapter contract, one registry, one shared prompt with no provider or model name in it (a test asserts this), and three adapters behind it. |

The two gaps that a user would notice are both in the tab: it cannot yet *tell* them to install or sign in,
and it cannot yet *offer* the hosted runtimes as real, registry-driven choices. Everything underneath is
built and tested.

---

## 3. What the previous agent built (commits `0bef2f9` … `d4f53c0`, plus the tree checkpointed as `9fac226`)

The prior session delivered most of plan phases 1 through 4, and a good part of phase 6. It was substantial,
careful work, and the security posture was already better than the plan required in places.

### 3.1 Session capability boundary: `src/gridlens/agent/session.py`

- `SessionContext` is a frozen dataclass written once to `<project>/agent/sessions/<UTC>_<suffix>/context.json`:
  project root, selected run ids, model, endpoint, session directory, session id.
- `scoped_path()` rejects absolute paths, `..`, symlinks at every path component, escapes from the root, and
  non-regular files. Every artifact read goes through it.
- `SessionContext.run()` refuses a run that is not in this session's selection, whose id is not
  `[A-Za-z0-9_.-]+`, or whose `status.json` is not `completed`.
- `load()` re-validates everything, including that the context file sits exactly where its own
  `session_id` says it should, so a moved or hand-edited context is rejected.
- Files are created with `O_NOFOLLOW` and mode `0600`; the session directory is `0700`.
- `export_session()` produces an opt-in audit zip from a fixed allowlist of names, deliberately excluding
  the `runtime/` directory (which holds the CLI profile), with a 64 MiB / 1000-file cap and an atomic
  `os.replace` through a temporary inode.

### 3.2 Deterministic tools: `src/gridlens/agent/tools.py` (15 tools)

`get_run_inventory`, `locate_run_artifacts`, `get_run_method`, `summarize_convergence`,
`rank_branch_loading`, `summarize_loading`, `list_thermal_violations`, `get_branch_loading`,
`search_buses`, `compare_runs`, `rank_contingencies`, `get_contingency_flows`,
`get_branch_contingencies`, `propose_analysis_script`, `get_script_result`.

- One `@tool` decorator centralizes the whole envelope: a per-call id (`T1`, `T2`, …) derived by counting
  `phase: started` lines under an `flock`, the result contract from plan §4.5, server-side row and byte
  caps the model cannot raise, string truncation, and an append-only two-line audit record per call in
  `tool_calls.jsonl`.
- Results are trimmed row-by-row until they fit `MAX_RESULT_BYTES`, and `truncated` is set honestly.
- Tools take logical run ids, never paths. Returned paths are relative to the project.
- Metric semantics follow plan §5: "most congested" is maximum observed utilization with the definition
  stated in the result; thermal margin is `100 - max_utilization_pct` in percentage points and is
  explicitly *not* transfer or generation capacity; the full canonical branch key
  (from bus, to bus, circuit, section) is never merged; failed or non-converged cases produce an explicit
  warning with a denominator.
- Reads prefer the compact `reports/interactive_tables/*.csv` cache (about 1.9 MB) over the 8.7 GB flat
  file, and verify cache freshness by comparing source/cache/manifest mtimes before trusting it. A stale or
  missing cache yields `ANALYSIS_NOT_BUILT` rather than silently starting a multi-minute build.

### 3.3 MCP server: `src/gridlens/agent/mcp_server.py`

Uses the official MCP Python SDK (`mcp==1.30.0`, pinned in `pyproject.toml` and collected by the
PyInstaller spec). `main.py` dispatches `--mcp-server` **before importing Qt**, and also offers
`--agent-tool` as a model-free developer CLI for calling one tool against an existing session context.
Tool annotations mark everything read-only except `propose_analysis_script`.

### 3.4 Hermes runtime adapter: `src/gridlens/agent/hermes.py`

- Writes a dedicated, throwaway Hermes profile per session under the session directory: only the GridLens
  MCP server, no bundled skills or plugins, no memory, no compression, no telemetry, no lazy installs, no
  external login adoption, tool search off.
- Launches `hermes chat --oneshot --format stream-json --toolsets gridlens --ignore-rules --no-restore-cwd …`
  with the prompt in a session file (never interpolated into a shell), `shell=False`, a minimal
  environment, its own process group, and group termination on stop or exit.
- Pins the validated CLI version (`0.21.4`) and refuses anything else rather than guessing a new event
  format.
- `parse_event` normalizes Hermes's structured events and **raises on any tool name that is not
  `mcp__gridlens__*`**.

### 3.5 Route enforcement: `src/gridlens/agent/policy.py`

`local_endpoint()` resolves the endpoint and requires *every* resolved address to be loopback, rejects
credentials in the URL, query strings, odd paths, and redirects, and disables proxies for the runtime
process. `verify_model()` additionally refuses Ollama cloud models and models without the `tools`
capability, before anything is sent.

### 3.6 Controller and GUI

- `AgentController` owns the canonical conversation, streams the child's stdout through a selector with a
  wall-clock deadline and byte caps, audits every normalized event, and kills the whole process group on
  stop, timeout, or error.
- `normalize_citations()` rewrites `[T3]`-style references and marks any call id absent from the audit as
  `[T3: invalid source]`, so an invented citation renders as invalid rather than as a source.
- `gui/agent_tab.py` provides the tab: runtime/model/run selectors, diagnostics, build-analysis control,
  transcript, activity, Sources panel, history browser, audit export, and script review.
- `gui/script_review.py` is the approve-and-run dialog; `gui/agent_jobs.py` wraps analysis builds.

### 3.7 Generated-script path: `src/gridlens/agent/scripts.py`

`propose_analysis_script` only ever *saves* code (AST-parsed, hashed, capped at 24 KiB, max 30 per
session). Execution is reachable only from the review dialog, requires the user to approve that exact
SHA-256, and runs in a container with no network, no GPU, read-only root, read-only run mount, dropped
capabilities, `no-new-privileges`, non-root uid/gid, and CPU/memory/pids/fsize/output/wall-clock limits.
Results are recorded as untrusted.

### 3.8 Analysis layer

- `analysis/service.py`: `AnalysisService`, a non-GUI, cancellable, `flock`-serialized build service in a
  spawned process group. **Already shared** by `gui/analysis_tab.py` and the Agent tab.
- `analysis/contingencies.py`: the compact `contingency_summary` table (thousands of rows, not tens of
  millions), produced during the same pass that aggregates the flat CSV.
- `analysis/event_index.py`: a bucketed Parquet contingency index (64 buckets by `event_idx`) built by
  streaming the flat CSV through PyArrow, published only after a complete build, with a manifest that
  records source size and mtime so a stale index is detected.
- Domain calculations live in `analysis/loading.py` / `utilization.py` and are called by both the GUI
  charts and the tools, as plan §5 required.

### 3.9 Tests it left behind

186 passed, 4 skipped at the start of this session. Notably `tests/test_agent_hermes_installed.py` contains
an excellent opt-in test that runs the **real** Hermes CLI against a synthetic loopback OpenAI-compatible
server, so the whole pipeline is exercised deterministically at zero model cost.

---

## 4. What this session did

### 4.1 Validated the feature against the user's real setup

This was the single most valuable result: the vertical slice genuinely works.

- **Real Hermes CLI, end to end** (`GRIDLENS_TEST_HERMES=1`): Hermes 0.21.4 launches the GridLens MCP
  server, is offered exactly the 15 GridLens tools and no built-in tool, calls `rank_branch_loading`,
  returns the right number, cites the audit call id, and resumes a second turn. Passed.
- **All six installed Ollama models passed** the evaluation with the identical prompt and tools:

  | model | seconds |
  |---|---|
  | qwen3.6:35b | 20.6 |
  | nemotron3:33b | 25.6 |
  | gemma4:31b | 53.8 |
  | gpt-oss:120b | 55.0 |
  | granite4.2:30b | 71.1 |
  | nemotron-3-super:120b | 72.6 |

  Note `llama3.3` is **no longer installed**; the plan's §3 baseline table is stale on that point.
- **Index layout benchmark on the real run** (`/home/alh360/GridLensProjects/GridPACK_Test_Project/runs/2026-07-28_14-46-26`,
  8,697,686,858-byte flat CSV, 74,701,440 indexed rows, PyArrow CPU, zero GPU memory):

  | layout | build | Parquet bytes | ratio | event query cold/warm | branch query | peak RSS |
  |---|---|---|---|---|---|---|
  | **buckets** (shipped default) | 101.5 s | 3,126,265,202 | 0.359× | 0.069 s / 0.058 s | 2.07 s | 2.02 GB |
  | sorted | 130.3 s | 2,532,316,449 | 0.291× | 0.127 s / 0.102 s | 2.75 s | 4.06 GB |
  | unpartitioned | 105.5 s | 2,532,590,577 | 0.291× | 0.170 s / 0.162 s | 5.49 s | 4.09 GB |

  The bucketed default wins on build time, query latency, and peak memory for 24% more disk. Plan §6
  demanded measured results before selecting a layout; this is that evidence. Raw output is in
  `$JOB/tmp/bench/*/benchmark.json`.
- **Hosted CLI facts**, captured live: Claude Code 2.1.278 and Codex CLI 0.155.1 are installed and signed
  in. `claude --print --output-format stream-json --verbose --restricted --tools "" --strict-mcp-config …`
  reports `"tools":[]`, `"mcp_servers":[]`, `"slash_commands":[]`, `"skills":[]` in its init event, which is
  exactly the isolation proof plan §4.3 demands. Codex could **not** be proven: `shell_tool` and
  `unified_exec` are stable, enabled features of `codex exec`, and `codex debug prompt-input` renders only
  the message list, not the tool inventory. Captured event schemas are in `$JOB/tmp/claude_events.jsonl`
  and `$JOB/tmp/codex_events.jsonl` (the Codex probe hit a ChatGPT usage limit, so only its
  `thread.started` / `turn.started` / `error` / `turn.failed` envelope was observed first-hand).

### 4.2 Made the feature genuinely model-agnostic (the user's explicit requirement)

The prior code worked but leaked Hermes into shared layers. New and changed files:

| File | Status | What it does |
|---|---|---|
| `agent/providers.py` | new | The seam. `ProviderDescriptor` rows for `hermes` / `claude` / `codex` carrying route, whether models are enumerable from an endpoint, whether an endpoint field applies, whether signing in applies; plus `descriptor()`, `route_for()`, `create_adapter()` with lazy imports so one runtime's dependencies cannot break the others. |
| `agent/process.py` | new | Provider-neutral subprocess mechanics lifted out of `hermes.py`: `minimal_environment(loopback_only=…)`, `mcp_command()`, `mcp_server_environment()`, `terminate_process()`, `run_probe()`, `probe_version()`. |
| `agent/prompt.py` | new | The single `SYSTEM_PROMPT` every runtime sends, with no provider or model name in it (a test asserts this), plus `turn_prompt()` which composes a turn and, for runtimes that cannot resume, a bounded replay of GridLens's own transcript delimited as untrusted prior context. |
| `agent/claude_code.py` | new | Working Claude Code adapter. Probe reports installed/signed-in/policy state. `prepare()` emits a session-only MCP config and an argv using `--restricted --tools "" --strict-mcp-config --allowedTools mcp__gridlens__* --permission-mode dontAsk --permission-prompts none --disable-slash-commands --no-session-persistence`. `parse_event()` asserts the init event's tool and MCP inventory and fails closed on anything foreign. Gated off by policy. |
| `agent/codex.py` | new | Probe-only Codex adapter, so the tab can still prompt install/login. `prepare()` fails closed with `ISOLATION_UNPROVEN` and the recorded reason. `session_argv()` and `parse_event()` are implemented and tested so the adapter is ready if `codex app-server` later makes isolation provable. |
| `agent/runtime.py` | rewritten | `RuntimeStatus` now carries `provider`, `route`, `authenticated` (None = not applicable), `policy_blocked`, `install_command`, `login_command`, `docs_url`, plus `installed` and `remote` properties. That is everything the GUI needs to describe a provider without knowing which one it is. The protocol gained `provider`/`label`/`route`/`supports_continuation`. |
| `agent/policy.py` | extended | The hosted gate: `HOSTED_GATE_ENV = GRIDLENS_ALLOW_HOSTED_AGENT`, `hosted_authorization()` returning `""` / `"proven"` / `"all"`, and `require_hosted_authorization(provider, isolation_proven)`. Default is closed. |
| `agent/session.py` | extended | `runtime` is validated against the registry instead of being hardcoded to `"hermes"`; new `route` and `remote_acknowledged` fields; `create()` decides the route *before* any user text exists, forces the endpoint empty for remote and loopback-validated for local, and refuses a remote session without an acknowledgement; `load()` re-validates all of it. |
| `agent/controller.py` | extended | Provider-neutral user-facing strings; a `runtime_label`; accumulates streamed text so a runtime that reports its answer only as deltas still produces a final answer; replays its own bounded transcript for adapters with `supports_continuation = False`. |
| `agent/hermes.py` | reduced | Now consumes `process.py` and `prompt.py`, declares its provider identity, and additionally rejects a session whose init event advertises non-GridLens tools. |
| `agent/scripts.py` | changed | Imports process helpers from `process.py` instead of from the Hermes adapter. |
| `tests/test_agent_providers.py` | new | 10 tests: every descriptor builds a contract-satisfying adapter; the prompt and tool surface name no provider or model; hosted runtimes stay closed without written authorization; a remote session records its route and needs an acknowledgement; Codex fails closed with its reason and its argv carries no dangerous flag; the Claude session exposes only GridLens tools and its manifest records the egress note; the Claude preflight refuses a session it does not control (4 cases); both hosted event streams normalize to the shared contract. |

**Suite after this work: 199 passed, 4 skipped.**

### 4.3 Found and verified 34 remaining defects

A seven-dimension analysis (provider seam, tool semantics, security/isolation, GUI/UX, tests, docs and
packaging, and defects in the least-reviewed diff) produced findings that were then each handed to an
independent adversarial verifier instructed to *refute* them. 34 survived: 16 major, 18 minor, no blockers.
The six provider-seam findings were fixed during the run and so do not appear in the surviving list.

**The full set, evidence plus an adversarially corrected fix for each, is committed as
`docs/plans/agent_findings.md`.** The corrected fixes matter: they routinely identify concrete errors in
the original proposal (a test that cannot pass because a fixture's CSV is header-only, a `toHtml()` that
does not exist on `QPlainTextEdit`, a one-liner that raises `IndexError` on an empty exception message, a
proposed mount narrowing that would break the user's own example questions). Follow the fix text rather
than re-deriving it from the summary.

For orientation, the 34 break down as: 7 in the GUI, 7 in the tool service, 8 in documentation, 7 in test
coverage, 2 in security error-handling, 2 correctness defects, and 1 packaging. Sixteen are major.

---

## 5. The remediation batch, and what actually landed

Eleven agents were dispatched to apply the 27 non-GUI findings across disjoint file sets. **All eleven were
killed by a session usage limit before they could report.** The workflow recorded zero successes.

That is not the whole story: four of them had already written their edits to disk when they died, and those
edits were snapshotted into `629d799`. Two of the four also left damage. Treat the following as the record
of what is genuinely done.

**Landed and verified working** (findings 1, 5, 12, 13, 14, 17, 28):

- **1, 5**: `tests/test_agent_runtime.py` now pins the Hermes adapter's exact argv and the manifest's
  `command_template`, so deleting `--ignore-rules` or `--toolsets gridlens` fails the suite, and
  `start_turn` is exercised directly. `tests/test_agent_mcp.py` gained fail-closed coverage for the
  `--mcp-server` and `--agent-tool` entry points, including that neither imports Qt.
- **12, 14**: `docs/security_ceii.md` no longer claims no AI model is involved, and it now documents the
  two different containers and their different mounts, so the solver rule and the sandbox rule no longer
  contradict each other. `CONTRIBUTING.md` and `docs/packaging_distribution.md` were updated to match.
- **13**: `packaging/agent/Dockerfile` is buildable (it was not), keeps `ANALYSIS_BASE` deliberately
  without a default so no floating tag can contradict the digest pin `scripts.py` enforces, and defaults to
  uid 65534. `packaging/agent/README.md` explains how to build and pin the image.
- **17**: `AnalysisService` grew a module-level `_terminate_group()`, unit-tested to prove a grandchild
  process cannot outlive a cancelled build.
- **28**: `gui/agent_jobs.py` now sends a one-line failure summary to the outcome label and the full
  detail to the activity pane, guarded so an exception with an empty message cannot raise inside the
  worker's own handler.

**Damage they left, since repaired in `2a7a2e9`:**

- `tests/test_agent_mcp.py` was written with a `pytest.mark.parametrize` but no `import pytest`, so the
  entire suite failed to collect. One line.
- A new test asserted that the `--agent-tool` CLI prints a stable error code, which it did not; it printed
  only the remedy. Fixed in `mcp_server.py` rather than by weakening the test, since the code is the
  contract plan §4.5 asks for and the `--mcp-server` entry point already printed it.

**Did not land at all** (findings 2, 3, 4, 6, 7, 8, 9, 10, 11, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26,
27, 29, 30, 31, 32, 33, 34). Seven of those are the GUI work that was never delegated in the first place.

The lesson worth carrying: agents killed mid-write leave syntactically broken files behind, and a workflow
reporting "0 succeeded" does not mean "0 changed". Always diff and run the suite before trusting the tree.

---

## 6. What still needs doing

Ordered by what a reviewer would demand first.

### 6.1 The Agent tab GUI, which is not started and is the user-facing half

`src/gridlens/gui/agent_tab.py` was deliberately reserved and is **unchanged** from the prior session. It
still hardcodes `HermesAdapter` and shows the two hosted entries as disabled placeholder strings. Everything
below it is now provider-neutral, so this is wiring, not redesign. Required:

1. **Registry-driven provider selector.** Populate the combo from `providers.DESCRIPTORS` (label + provider
   id as item data). On change, start a new session and re-probe.
2. **Per-provider probe.** `RuntimeProbe` should take a provider id and call
   `create_adapter(provider, endpoint).probe()`.
3. **Install and login prompts**: the user asked for this explicitly. Drive them from the new
   `RuntimeStatus` fields: `installed`, `authenticated` (None means signing in does not apply, as for local
   Ollama), `install_command`, `login_command`, `docs_url`, `policy_blocked`. Show the command in a
   read-only, selectable field with a copy button, plus the vendor documentation link. GridLens must not
   run installers or login flows.
4. **Local/Remote route badge** with the consequence spelled out for remote, per plan §8.
5. **Remote acknowledgement checkbox**, shown only for a remote provider, required before Send, and passed
   to `SessionContext.create(..., remote_acknowledged=…)`. Without it `create()` raises
   `REMOTE_NOT_ACKNOWLEDGED`.
6. **Per-provider fields.** Show the endpoint row only when `descriptor.needs_endpoint`; make the model
   combo editable when `not descriptor.enumerates_models` (hosted runtimes take a typed model name, where
   `"default"` means the CLI's own default).
7. **Create the adapter from the session**, not from a hardcoded class:
   `create_adapter(context.runtime, context.endpoint)`.
8. Finding **2**: `on_event` calls `update_sources()` unconditionally on every streamed event, and each call
   re-reads and re-parses the whole `tool_calls.jsonl` on the GUI thread. Call it only where the audit can
   have changed (`tool_result`, and at completion).
9. Finding **4**: `refresh_runs()` / `select_run()` can retarget the selection mid-turn, which calls
   `new_session()` and wipes the transcript of a running conversation. Add a `_can_retarget()` guard
   covering both the turn worker and the analysis worker, inside `refresh_runs` so both entry points are
   covered.
10. Finding **18**: `text` events are audited but never rendered, so the transcript sits blank for the whole
    turn. Render streamed text incrementally (append at the cursor during streaming; rebuild once at
    completion so the citation-normalized final text replaces the stream). Do not rebuild the document on
    every delta.
11. Finding **19**: the hosted gate's reason exists only as a collapsed item tooltip. Make it visible.
12. Finding **20**: separate the channels. `diagnostics` currently receives runtime status, analysis
    outcomes, and every caught exception. Reserve it for runtime probe status and route the rest to the
    activity pane.
13. Finding **21**: the Sources panel parses the audit record but drops `result["error"]` (code and remedy)
    and `result["warnings"]`. Render them, and build each block defensively with `.get()` because
    `update_sources` also runs over older session files from the history browser.
14. Finding **3**: `tests/test_agent_gui.py` line 23-24 is tautological, because it asserts Qt's own plain-text
    round-trip. Replace it with a real safe-rendering assertion. Use `tab.transcript.document().toHtml()`;
    `QPlainTextEdit` has no `toHtml()`.
15. `gui/main_window.py` line 100 still reads "Ask a local Hermes agent about selected completed runs."
    Make it provider-neutral. No agent owns that file.

### 6.2 The other 20 open findings

Everything in `docs/plans/agent_findings.md` that is still marked **open** and is not GUI work. Grouped by
the file they touch, because that is how they should be batched:

- **`src/gridlens/agent/tools.py`**: findings 15, 29, 30, 31, 32, 33, 34. The two that matter most are 15
  (an unhandled exception type escapes the result envelope, leaving an unpaired `started` record in the
  audit and returning a raw Python message to the model, which breaks the stable-error-code contract) and
  30/31 (the same missing existence guard in `_optional_table`, which turns a merely absent optional table
  into an error instead of a graceful fallback). 32, 33 and 34 improve answer quality for the user's own
  example questions: more of the recorded study settings, bus lookup that tolerates PSS/E name padding,
  and telling the reader which facilities a filter excluded.
- **`src/gridlens/analysis/{csv_flat,event_index,contingencies}.py`**: finding 16, the most delicate one
  left. The streaming row path, the accelerated frame path, and the Parquet index disagree on how a circuit
  id such as `1.0`, `01` or `'1'` is canonicalized, so a drill-down query can silently miss rows. The fix
  is one shared null-safe canonicalizer called from all three producers, with the operation order right.
- **`tests/test_agent_tools.py`**: findings 6, 8, 22. Five of the fifteen tools have no test, the metric
  semantics the plan enumerates are unasserted, and nothing pins the untrusted-data caps. Do **not** extend
  the shared fixture in `tests/conftest.py`; several existing assertions pin exact counts derived from it.
- **`tests/test_agent_hermes_installed.py`**: finding 7, a real scored evaluation across plan §11's seven
  dimensions instead of one collapsed assertion.
- **Documentation**: findings 9, 23, 24 (the plan document), 10 and 27 (user guide, troubleshooting), 11
  and 26 (architecture, developer guide, README), 25 (the csv_flat reference). The measured numbers these
  documents need are all in §4.1 of this handoff.

### 6.3 Re-run the real-runtime validation at the end

The end-to-end proof in §4.1 was measured before any of the remediation work. Re-run it once the tree
settles:

```
cd /home/alh360/Documents/gridpack-workbench-dev
GRIDLENS_TEST_HERMES=1 .venv/bin/python -m pytest tests/test_agent_hermes_installed.py -q -s -k "isolation or resumes"
GRIDLENS_TEST_LOCAL_MODELS=1 GRIDLENS_TEST_MODEL_NAMES=nemotron3:33b,qwen3.6:35b \
  .venv/bin/python -m pytest tests/test_agent_hermes_installed.py -q -s -k local_models
```

The first of those is the valuable one: it drives the real Hermes CLI against a synthetic loopback model
server, so it exercises profile isolation, MCP discovery, the tool surface, citations and continuation
deterministically and at no model cost. It runs in about five seconds.

Then exercise the tab in the real app against the real project, which no automated test covers. Note that
the reference run's cached tables were built at dataset/parser version `2026.07.05`, so the tools will
correctly answer `ANALYSIS_NOT_BUILT` until Build / refresh analysis is run. That is itself worth testing,
because it is the path a first-time user hits.

### 6.4 Still deferred by the plan, deliberately

- **Hosted inference stays off.** `CONTRIBUTING.md` forbids sending inputs, outputs, manifests, or derived
  exports to online services. The Claude Code adapter is complete and its isolation is proven, but
  `GRIDLENS_ALLOW_HOSTED_AGENT` must remain unset until a written governance decision changes
  `CONTRIBUTING.md` and `docs/security_ceii.md` and defines authorized data classes, approved providers and
  accounts, retention, residency, incident response, and administrator control. Do not flip this as part of
  a feature change.
- **Codex** needs `codex app-server` evaluated before it can be more than probe-only. Revisit if a future
  CLI lets a caller prove the effective tool inventory. The adapter is written and tested; only the
  isolation gate blocks it.
- **Opt-in tests that were never run here:** `GRIDLENS_TEST_SANDBOX_IMAGE` (needs a digest-pinned image
  built from `packaging/agent/Dockerfile`, which could not be built as written, per finding 13) and
  `GRIDLENS_TEST_SAMPLE_PROJECT` (the read-only cache benchmark against the real project).
- **Multi-turn behaviour for a replay-based adapter** is implemented but untested against a real hosted CLI,
  because that would require opening the egress gate.
- **PyInstaller and Debian packaging** were not rebuilt this session. `mcp==1.30.0` is pinned and the spec
  collects it, but plan phase 2's exit criterion has not been re-confirmed since the agent
  package grew. That criterion is the frozen and packaged entry points passing the same tests as the
  source entry point.

---

## 7. Traps worth knowing

- **A workflow reporting zero successes can still have changed files.** Four of the eleven killed agents
  had already written to disk, and two left syntactically broken files. Diff and run the suite before
  trusting any tree an interrupted batch touched.
- **The 8.7 GB flat CSV is real.** Never read it whole. The tools deliberately read the ~1.9 MB cache and
  the bucketed Parquet index instead, and `MAX_TABLE_BYTES` exists to stop accidents.
- **Cache freshness is an mtime sandwich**: source ≤ cache ≤ manifest. Writing a fixture's CSV after the
  manifest silently invalidates it, which is why one proposed test in the defect register cannot pass as
  written.
- **Do not extend the shared `tests/conftest.py` fixture rows.** Several existing assertions pin exact
  counts and averages derived from them, and the fixture's CSV field list comes from the first row's keys.
- **`RuntimeStatus` is constructed positionally in older call sites** (`ready, message, executable,
  version, endpoint, models`). The new fields were appended with defaults to keep those working; keep that
  ordering stable.
- **`AnalysisService` uses a uid-keyed `flock` in `/tmp`.** Parallel test runs contend on it by design
  (the waiter is cancellable), but it makes concurrent suite runs look flaky.
- **Concurrent agents in one checkout** work only with strict file ownership. Two agents in the same file
  will silently lose each other's edits.
- **`cufile.log` is tracked and routinely dirty.** It is unrelated GPU-I/O build noise; keep it out of
  commits.
- **Do not flip `GRIDLENS_ALLOW_HOSTED_AGENT` as part of a code change.** It is the CEII gate. See §6.4.

---

## 8. Quick verification

```
cd /home/alh360/Documents/gridpack-workbench-dev
.venv/bin/python -m pytest -q          # 209 passed, 4 skipped as of 2026-09-22
.venv/bin/python -m compileall -q src tests
git diff --check
```

The four skips are the opt-in tests that need an installed CLI, live local models, a prepared sandbox
image, or the real sample project. Two of them were run by hand this session and passed (§4.1); the other
two have never been run (§6.4).
