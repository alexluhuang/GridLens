# AI planning agent verification (2026-09-22)

The Agent tab probes a user-installed runtime, creates sessions scoped to selected completed runs,
and asks models to call 15 deterministic GridLens tools. GridLens provides no model or inference.
Hosted providers can be inspected for installation and sign-in, but project prompts remain blocked
by the current local-only CEII policy. The installed Codex CLI also lacks a proven tool-isolation
path; its adapter fails closed.

## Automated checks

| Why | Method | Outcome | Interpretation |
|---|---|---|---|
| Verify tool contracts, parsing, GUI controls, runtime boundaries, and package metadata without a model | `.venv/bin/python -m pytest -q` on synthetic fixtures | 233 passed, 5 opt-in tests skipped | The deterministic paths and local policy gates passed; this does not measure model answers. |
| Recheck the changed runtime, tool, GUI, and event-index paths | `.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_agent_gui.py tests/test_agent_tools.py tests/test_event_index.py -q` | 64 passed | Catches regressions in citations, provider controls, scopes, branch keys, and tool result envelopes. |
| Exercise the real Hermes CLI without model variability | `GRIDLENS_TEST_HERMES=1` with the synthetic loopback OpenAI-compatible server | Passed the two-turn continuation and tool-isolation test | Hermes exposed only the 15 GridLens MCP tools, returned the fixture's 120% loading, and resumed a follow-up turn. |
| Check a representative large run without parsing its flat CSV into the agent | `GRIDLENS_TEST_SAMPLE_PROJECT=/home/alh360/GridLensProjects/GridPACK_Test_Project GRIDLENS_TEST_SAMPLE_RUN=2026-07-28_14-46-26` on the read-only cache benchmark | Two ranked-loading calls: 1.739 s and 1.893 s; Python traced peak 55,510,993 bytes; 6,823 matching facilities | The 8,697,686,858-byte flat CSV was referenced as provenance while compact caches answered the question. The memory figure is Python allocation peak, not process RSS or a cold-build measurement. |

The five default skips are the opt-in Hermes, scored installed-model, complete-voltage-group,
real-project, and pinned-sandbox-image checks. The sandbox execution test needs an operator-prepared
immutable image ID; unit tests cover the
container command and approval gate. No image was pulled or built by GridLens.

## Local model evaluation

The scored test uses the same synthetic project, shared system prompt, and tool catalog for every
model. It asks for (1) the most congested non-transformer line and confidence, (2) the largest
thermal margin, (3) a comparison with an unselected run, and (4) loading after deliberately making
the cache manifest stale. Each question starts a fresh session. The JSON report records individual
criteria, elapsed time, and session paths; per-session tool audits support the scores. Hard assertions cover the source-backed
number, citation, run isolation, and refusal to invent loading from a stale cache.

| Model | Outcome | Interpretation |
|---|---|---|
| `gemma4:31b` | 16/16 scored criteria; 173.037 s across four questions | Called the expected tools, gave 120% maximum loading and 20 percentage points of margin with citations, disclosed limits, refused unselected-run access, and requested a cache rebuild. |
| `nemotron3:33b` | 16/16 scored criteria; 96.051 s across four questions | Called the expected tools, gave the 120% and 20-point results, cited the congestion result, disclosed limits, refused unselected-run access, and requested a cache rebuild. An earlier continuation run timed out after repeatedly passing an invalid margin metric; the shared prompt now states the exact `thermal_margin_pct_points` argument and each scored question uses a fresh session. |

The two opt-in commands used were:

```bash
GRIDLENS_TEST_LOCAL_MODELS=1 GRIDLENS_TEST_MODEL_NAMES=gemma4:31b GRIDLENS_TEST_EVAL_OUTPUT=/tmp/gridlens-gemma4-evaluation.json .venv/bin/python -m pytest tests/test_agent_hermes_installed.py -q -s -k local_models
GRIDLENS_TEST_LOCAL_MODELS=1 GRIDLENS_TEST_MODEL_NAMES=nemotron3:33b GRIDLENS_TEST_EVAL_OUTPUT=/tmp/gridlens-nemotron-final-evaluation.json .venv/bin/python -m pytest tests/test_agent_hermes_installed.py -q -s -k local_models
```

Scores measure this fixture and one sample per model; they do not establish statistical reliability
or engineering validation of generated prose. Deterministic tools remain the source of numbers and
provenance. The controller also identifies omitted citations, truncated tool results, stale-cache
errors, and the physical limit of thermal margin in the final response.

## Truncated-result regression

**Rationale.** In a real session, a 10-row congestion ranking was used to invent whole-run voltage
means. A later request for 7,000 rows was silently capped at 50. The runtime saved those 50 returned
rows in a spillover file, which the model then described as if it contained all 6,823 matching lines.

**Method.** The deterministic tests check explicit rejection above the 50-row cap, byte-limit
truncation, audited returned/total counts, and full-population means despite a short ranked result.
The controller test simulates a model choosing `facility='all'` for a line-only mean question and
checks that GridLens calls `summarize_loading` again with `facility='line'`. The installed-model
regression extends the synthetic fixture to 11 eligible lines in three voltage groups, with one
transformer that must stay out of a line-only mean. It asks the same question of Nemotron 3:33b and
Gemma4:31b through Hermes. The report is `/tmp/gridlens-voltage-group-evaluation.json`.
Separate controller tests check that a top-line area question uses both audited endpoint labels
and that a singular follow-up refers to the prior audited top line, instead of repeating guessed
area names.

**Outcome.** Both final model sessions reported the full 11-line means: 230–344 kV 103.3% (3 lines),
345–499 kV 60.0% (4), and 50–99 kV 40.0% (4). Gemma4 selected the correct scope itself. Nemotron
selected all facilities; the controller recorded a second, line-only call and based the final answer
on that corrected result. A read-only check of the real project's compact cache produced the chart's
figures from 6,823 eligible lines: 345–499 kV 50.8% (351), 50–99 kV 49.5% (2,517), and 100–229 kV
39.2% (3,955). A 50-row ranking returned 17 rows under the new 16 KiB result cap; the summary still
used all 6,823 lines. A 7,000-row request now returns `LIMIT_EXCEEDS_CAP` rather than claiming success.

**Interpretation.** The short ranked view supports top-line questions, while the separate summary
supports group means over the full matching population. The live model result verifies one question
per model on a synthetic case; the real-project check verifies the deterministic summary against the
displayed chart, without claiming a full GUI acceptance test.

## Frozen and installed entry points

PyInstaller 6.20.0 built the final source into `/tmp/gridlens-agent-final3-dist/GridLens/` on the DGX Spark's
Linux aarch64 environment. The Debian build copies the sandbox
Dockerfile and README under `/usr/share/doc/gridlens/agent-sandbox/`, so installed users can prepare
their own pinned image. The official MCP SDK conformance test runs against both the frozen bundle
and the executable extracted from the `.deb`; this checks stdio dispatch before Qt and the 15 tool
schemas without installing the package or touching a project.

| Why | Method | Outcome | Interpretation |
|---|---|---|---|
| Check the frozen agent entry point | `GRIDLENS_TEST_MCP_EXECUTABLE=/tmp/gridlens-agent-final3-dist/GridLens/GridLens .venv/bin/python -m pytest tests/test_agent_mcp.py -q` | 5 passed | The bundled executable starts the GridLens MCP server and passes the SDK client contract. |
| Check the Debian install layout and entry point | Built `/tmp/gridlens-agent-final3-packages/gridlens_0.1.0_arm64.deb`, extracted it under `/tmp/gridlens-agent-final3-extracted/`, and reran the same MCP test against `opt/gridlens/GridLens` | Package metadata is `gridlens 0.1.0 arm64`; sandbox Dockerfile and README are present; 5 passed | The packaged binary and the user-facing sandbox recipe are present and functional in the extracted layout. This was not a desktop GUI smoke test or a system installation. |

The final source also passed `.venv/bin/python -m compileall -q src tests` and `git diff --check`.

## Deployment limits

Hosted prompts remain unavailable until the CEII policy changes, and Codex needs an isolation proof
for its built-in tools. The agent uses existing compact analysis caches; a missing or stale cache
requires the user to press **Build / refresh analysis**. Generated code is saved for audit and needs
explicit review and an operator-prepared pinned sandbox image before execution.

## Conversation UI verification (2026-09-23)

**Rationale.** The previous Agent tab separated the transcript from activity and sources. A user could miss
tool limits while reading an answer, and the setup controls left little space for the conversation.

**Method.** Ran `tests/test_agent_conversation.py` and `tests/test_agent_gui.py` with Qt offscreen, covering
plain-text rendering, Enter and Shift+Enter, live answer replacement, tool arguments and audited counts,
process collapse, saved-session replay, and unavailable reasoning. Rendered the tab offscreen at 1050×720
and 760×560, inspected both screenshots, and checked that expanded setup controls fit at the smaller size.

**Outcome.** The focused suite passed (10 tests). The desktop view showed user and agent text plus process
cards in one scroll area; the small view retained scrollable setup and chat controls without horizontal
clipping. Hermes' tested event stream provides tool events and answer text but no reasoning text, so the
process card reports that limitation and displays reasoning only if a runtime supplies it.

**Interpretation.** These checks verify the widget behavior and layout on an offscreen Qt platform. They do
not measure legibility on every display scale or demonstrate a live model turn in the redesigned tab.

**Broader regression check.** `.venv/bin/python -m pytest -q --ignore=tests/test_csv_flat.py` passed with
243 tests and 5 opt-in skips. Nine CPU and analysis tests selected from `tests/test_csv_flat.py` also passed.
The unrestricted suite was interrupted after 153 passes and 5 skips while a CSV acceleration test imported
RMM; other local model evaluations were using the same GPU. The 15 deselected CSV tests therefore remain
unverified in this run. The GUI change does not alter CSV parsing or acceleration code.

## Generalized rank tools (2026-09-23)

**Rationale.** The fixed-purpose loading tools answered only the question shapes they were written for, so
a model asked anything else averaged the rows it could see. `rank` and `rank_groups` let the model name the
objects, metric, group statistic, order, count, and qualifiers, while GridLens does the sorting and
arithmetic over every facility in scope.

**Method.** Six new deterministic tests cover sorting and `magnitude`, qualifiers on either-end fields,
unknown values, every statistic against hand-computed values, grouping, validation errors, the controller
accepting an equivalent `rank_groups` mean, and the typed qualifier schema through the official MCP client.
A read-only check of the sample project wrote its audit outside the project. Local models answered through
Hermes: the synthetic voltage-group regression, the synthetic congestion questions, and three questions
against a scratch copy of the sample run's compact caches.

**Outcome.** The full suite, including `tests/test_csv_flat.py`, passed with 267 tests and 5 opt-in skips.
On the sample run's 6,823 lines, the mean of `max_utilization_pct` by
voltage class was 50.762963% (351), 49.485785% (2,517), and 39.173937% (3,955), the Branch Analysis figures.
Lines above 100% by control area were Coast 45, North Centra 34, East 22, South Centra 13, Far West 10,
North 5, and West 3. Standard deviation, median, and interquartile range for three areas matched Python's
`statistics` module, and each call took about 0.37 s.

nemotron3:33b called `rank` with the right metric for the congestion and thermal margin questions, and
`rank_groups` with a qualifier above 100% for the area count. In one of two voltage-group runs it chose the
correct `rank_groups` arguments; in the other the controller repaired the scope. Hermes rejected malformed
nemotron calls to `rank` (the Coast question below) and `compare_runs` (the synthetic cross-run question),
which ended the congestion evaluation before gemma4:31b answered it. gemma4:31b first grouped "voltage
groups" by `nominal_kv`; after the `rank_groups` description named `voltage_class` as the Branch Analysis
voltage groups, it chose `voltage_class`. It answered the area count and the three most loaded lines at 345 kV
or above in Coast (104.35%, 98.9%, and 97.05%, of 59 matching lines), which an independent filter of the
cached rows reproduced. For the original transcript question, both models used `rank_groups` with
`object='both'`; the controller's line-only check then reported 50.8%, 49.5%, and 39.2%.

**Interpretation.** The tools compute whole-population statistics correctly, and both models filled in
groups, statistics, and qualifiers. Each question was asked once, and nemotron3:33b sometimes produced
malformed calls, so the controller checks remain necessary. Complex power and bus voltage are not metrics
yet: the compact caches hold loading percentages, not MVA flows or bus voltages.

## Saved-conversation continuation regression (2026-09-23)

**Rationale.** Refreshing the conversation list after a turn selected the placeholder while the active chat
remained on screen. Selecting the same saved session then opened a read-only replay and disabled Send.

**Method.** Qt offscreen tests finish a synthetic turn, refresh the selector, reopen the active entry,
and load an older saved session with tool activity and a runtime continuation ID. They check the selected
model and runs, Send state, and that Send reuses the saved session. A controller test removes the runtime ID
and inspects the next prompt for bounded transcript replay.

**Outcome.** The focused GUI and controller suite passed (38 tests), as did the full default suite
(270 passed, 5 opt-in skips). The active session stays selected; reopened sessions accept follow-up prompts
with their original scope. When a CLI resume ID is unavailable, GridLens supplies prior user and assistant
messages in the next prompt. The installed Hermes test also passed (1 test): it completed a turn, rebuilt
the controller from the saved session, and completed a follow-up through the restored runtime ID.

**Interpretation.** The GUI checks cover session selection and prompt construction without launching a model;
the Hermes loopback test verifies persisted continuation with its installed CLI and a synthetic model API.
It does not test an answer from a live Ollama model.

## Planning-question evaluation after the tool consolidation (2026-09-23)

**Rationale.** The consolidation replaced 35 tools with 15 general ones, so a model must fill in parameters
and chain calls rather than pick a tool per question. The user's 30 planning questions test whether a local
model can, across inventory, provenance, the RAW case, convergence, loading, margin, ties, contingencies,
voltages and angles, run comparison, setup, scripts, communication, scope, and robustness.

**Method.** gemma4:31b through Hermes 0.21.4 and Ollama, at a 262,144-token context, used the tools of
`c0e500d`. It answered 32 prompts: questions 2 and 30 in two variants each, and 24 as the follow-up to 23.
Each ran in a fresh session on a prepared copy of the sample project, `/home/alh360/GridLensProjects-eval2`,
with a load-shift comparison run, a run without analysis, and a failed run. Answers were scored against
each question's criterion and against reference facts computed from the data.
`scripts/prepare_agent_evaluation.py`, `scripts/agent_question_references.py`, and
`scripts/evaluate_agent_questions.py` do the work; `agent_question_evaluation.md` gives the steps for another
model. The run began with nemotron3:33b as well, which was stopped after two prompts at the user's request.

**Outcome.** 11 prompts passed, 16 partly passed, and 5 failed. They took 193 minutes, a median of 176
seconds each, with 130 audited tool calls. `agent_evaluation_gemma4_31b.md` gives every question, the exact
answer, each tool call, and the verdict and rationale. Preparing the run found two defects, fixed before it
began: generator outages had no outage area (`12b976d`), and a count by status dropped failed contingencies
(`c0e500d`).

**Interpretation.** When gemma chose the call, the tools gave exact answers, including:
- status counts, margins, contingency rankings, per-outage flows, and run changes;
- a complete create, configure, run, and wait sequence;
- a filing draft whose citations all resolve.

Most partial scores omit a caveat or scope the criterion asks for. The failures are:
- an XML replaced without confirmation;
- a claimed MVA headroom;
- an answer whose cited query named an area that does not exist;
- overloads classified by a count that includes GridPACK violation flags;
- a file question answered with no call.

The answers expose seven gaps, listed in the report, that are the next work. The largest are:
- no tool text on selecting tie lines with two `control_area` qualifiers, which cost 18 to 26 minutes on
  each of three questions;
- a confirmation rule held only in the prompt.

Each question was asked once, so the scores describe this sample, not a model's reliability.
