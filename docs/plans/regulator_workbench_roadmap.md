# GridLens roadmap: a regulator's transmission utilization workbench

Status: proposal, 2026-09-23. This is a product and implementation roadmap, not a claim that the features below exist.
It scopes the next phase of work after the present Agent tab, which remains documented in
[the agent plan](ai_planning_agent.md).

## Product decision

GridLens should help a nontechnical reviewer answer: **What was studied? What loading was observed? Where and under
which outage? How complete and comparable is the evidence? What should I ask the study author next?** It should show
the result in plain language, preserve the underlying figures, and make the path from a statement to a run artifact
one click long. A technically trained reviewer should still be able to inspect the exact configuration and rows.

Draw on [PowerMCP's](https://github.com/Power-Agent/PowerMCP) pattern of small, well-defined tools and
[GridMind's](https://arxiv.org/abs/2509.02494) coordinated study concept, while keeping one GridLens/GridPACK
data and execution boundary. GridMind's paper does not establish a tested recovery design for long-running
workflows; the state and restart behavior proposed here are GridLens requirements. GridLens already has a tool
server, persistent agent conversations, background GridPACK and analysis jobs, and large-result indexing. The
missing layer is a durable *study workflow* that coordinates those parts and explains their evidence to a
regulator. A separate swarm of model agents is not a prerequisite; the workflow state should be deterministic
and visible regardless of model.

### Scope and vocabulary

- **In scope:** PSS/E RAW case intake, the configured GridPACK base and contingency runs, monitored transmission
  line and transformer loading, thermal rating utilization, convergence/coverage, event and facility drill-down,
  comparison of runs made from user-supplied cases, and audit-ready explanations.
- **Conditional:** statements about a future year, seasonal peak, upgrade, or policy case require the user to supply
  a matching case and label its provenance. GridLens may compare submitted cases; it must not invent a forecast,
  dispatch, outage set, or engineered remedy.
- **Outside this data boundary:** market congestion cost, production cost, ratepayer benefit, project cost, siting,
  customer outage risk, resource adequacy, deliverability, interconnection queue capacity, available transfer
  capability, total transfer capability, and whether a project meets a regulatory or reliability obligation.
  These require other data and methods. GridLens should say what evidence is missing and suggest a question for
  the responsible planning entity.
- Say **"thermal loading"**, **"rating exceedance"**, and **"unused portion of this facility's rating in this
  simulated case"**. Avoid using "congestion" without qualifying it as *thermal*; many readers will hear market
  congestion and costs. `100 - utilization_pct` is a thermal rating margin in percentage points, not MW of
  transferable energy or interconnection headroom. An overload is a screening finding in the supplied study,
  not proof of an actual outage or of a preferred project.

This boundary follows the supplied planning references. [CAISO's updated 2025–2026 plan](https://www.caiso.com/documents/board-approved-2025-2026-transmission-plan.pdf)
separates reliability, policy, and economic assessments; its economic assessment uses production cost simulation.
[MISO's one-page planning explainer](https://cdn.misoenergy.org/At%20a%20Glance%20Summary%20-%20Transmission759373.pdf)
shows why a public-facing summary must distinguish reliability, cost, integration, and coordination questions.
[NERC's ITCS overview](https://www.nerc.com/pa/RAPA/Documents/ITCS_Overview.pdf) defines transfer capability as
an incremental transfer study under specified conditions and explicitly limits what even that study establishes.
The [DOE July 2026 *draft* Needs Study](https://www.energy.gov/documents/national-transmission-needs-study-draft-july-2026)
uses multiple kinds of evidence and assesses needs rather than choosing solutions. [FERC's Order No. 2023
explainer](https://www.ferc.gov/explainer-interconnection-final-rule) discusses cluster studies and a public
available-capacity heatmap; a GridLens loading view is neither of those. The five user-supplied copies are in
`/home/alh360/Downloads/` and were used as the reference set; the links above are the issuers' versions.

## What the present system can support

| Available now | Useful regulator question | Boundary |
| --- | --- | --- |
| Project inputs and hashes; run manifest, XML, status and logs | "Which case and settings produced this?" | The project currently lacks a study purpose, case vintage, scenario author, and review state. |
| RAW/bus metadata: facility keys, names, voltage classes, endpoint control areas, ratings where present | "Which line or area does this refer to?" | No verified geographic coordinates; area labels are model metadata, not a map. |
| Flat CSV rows: monitored facility, event, loading; compact facility and contingency summaries | "Where was loading highest, and during which modeled outage?" | Summary statistics cover recorded rows and the selected monitor scope, not every system condition. |
| Convergence/status CSV and run logs | "Which events failed or have uncertain coverage?" | A failed event cannot be treated as a zero-loading event. |
| Optional event-indexed Parquet and file tools | "Show the rows behind this finding." | Index building takes time and disk; ordinary views should use cached reductions first. |
| Existing Branch/Transformer Analysis charts, agent analysis and operation tools, persistent jobs | "Explain, drill down, and run the next study." | Jobs persist, but there is no checkpointed multi-step review workflow. |

See [architecture](../architecture.md), [CSV flat behavior](../csv_flat_ca_scalability_v2.md), and [CEII notes](../security_ceii.md).
In particular, `csv_flat` supplies `loading_percent` directly; the legacy text path uses MW divided by RAW Rate C.
These are not automatically identical physical measures. A future comparison must display and validate its metric
source before combining or ranking results from different formats.

## Reviewer journeys to design around

1. **Open a submitted study.** "What case is this, who supplied it, what does it represent, and what was actually
   run?" Outcome: a one-page study brief with input hashes, user-entered scenario description, run method, scope,
   source files, and missing metadata marked *unknown*.
2. **Screen for concerns.** "Which monitored facilities exceeded the selected thermal rating in the base case or
   a converged contingency?" Outcome: count, denominator, top facilities, binding events, threshold, and a link
   from each figure to source rows. No list of ten displayed rows may stand in for a population statistic.
3. **Understand an area.** "Which studied lines touch this control area, and what happens under each outage?"
   Outcome: area summary with crossing ties labeled and a drill-down. A tie in two areas must not be added twice
   to produce a system total.
4. **Compare submissions.** "Did the revised case change these observations?" Outcome: paired runs and explicit
   differences in inputs, rating, monitors, and outage coverage; common-facility results and unmatched items
   are separate. Do not call a difference an upgrade benefit unless the changed assumptions are documented.
5. **Prepare questions or a record.** "Which findings need explanation from the utility, and what evidence is
   missing?" Outcome: a review queue, citations, coverage limits, and a frozen evidence package.

## Milestone order and exit gates

Milestones are ordered by dependency rather than a calendar estimate. "P0" means needed before regulator-facing
claims; "P1" is the first complete review journey; "P2" deepens analyses; "P3" coordinates long studies.

| Milestone | Deliverable | Exit gate |
| --- | --- | --- |
| **P0 — Trust contract** | Shared metric and provenance contract, coverage reporting, wording rules, independent reference fixtures | GUI, exports, and agent agree on every tested value and denominator; no failed event is shown as zero. |
| **P1 — Guided case review** | Study brief, case intake, plain-language run preflight, study home, basic evidence dashboard | A new reviewer can identify the case, rating, monitor scope, run outcome, top finding, and one limitation without reading XML or a raw CSV. |
| **P2 — Comparative evidence** | Facility/event drill-down, distributions, matched-run comparisons, review queue, frozen export | Every chart number opens the matching table/filter; a mismatched comparison is labeled or blocked. |
| **P3 — Coordinated agent** | Durable workflow plans, background job orchestration, resume/cancel, evidence-grounded answers | A multi-step study survives app restart and returns to the same selected conversation, plan, and artifacts. |
| **P4 — Release validation** | DGX Spark performance, accessibility and comprehension testing, local-model eval, CEII review | Numeric and scope gates below pass on both synthetic fixtures and a large real run. |

The first useful release can stop after P1. P2 and P3 should reuse its evidence contract rather than redefine
metrics inside charts or prompts.

## Feature backlog by surface

### UI and accessibility

| ID / priority | Change | Acceptance |
| --- | --- | --- |
| UX1 / P1 | Add a **Study home** with three visible questions: "What was studied?", "What was found?", and "What remains unknown?" Keep Project, Configuration, Run, and Analysis as drill-down destinations. | Opening a run lands on its scope and result summary; every summary card links to the exact run and source table. |
| UX2 / P1 | Use a consistent plain-language layer: "modeled outage" with "contingency" in help text; "loading as % of selected rating" instead of an unexplained percentage. Put units and denominator next to numbers, with a short expandable method note. | User-facing cards, charts, exports, and agent answers use the same approved terms and rating label. |
| UX3 / P2 | Add keyboard-accessible table and chart alternatives, visible focus, readable color/contrast, text patterns for exceedances, and saved filter state per run. | Every chart fact is available in a sortable table and to a screen reader; color alone never conveys status. |
| UX4 / P3 | Keep chat, reasoning/tool activity, and workflow progress in one conversation; persist its selected project, run, and workflow IDs. Show completed steps and resumable jobs as messages. | Switching tabs or reopening the app does not create an unexplained "current conversation" or strand an earlier session. |

### Project management and case setup

| ID / priority | Change | Acceptance |
| --- | --- | --- |
| PM1 / P1 | Add optional, versioned study metadata to existing projects: purpose/question, source organization, RAW case identifier and vintage, user-supplied season/condition and planning horizon, owner/reviewer, sensitivity label, and notes on assumptions. Never infer these from a filename. | Existing `project.json` files open unchanged; missing fields visibly say *not provided*. |
| PM2 / P1 | Provide an intake wizard that previews RAW network, areas, kV distribution, branch/transformer counts, duplicate or unresolved keys, ratings, XML references, and file hashes before saving. | The wizard reports a specific fix for missing references or invalid files and records exactly which files were imported. |
| PM3 / P1 | Add a **case register**: each case is an immutable input/configuration snapshot with a readable label and its source hashes; runs point to a snapshot. Let users mark a submitted revision or sensitivity and record what the submitter says changed. | A later replacement of `original_inputs/` cannot silently relabel an old run; old manifests remain readable. |
| PM4 / P2 | Add project/run search by labels, source, area, date, and review status; permit pinning two submitted cases for comparison. | A reviewer can recover the exact prior run from a saved finding, even if a newer run exists. |

The case register is an evidence catalog, not an automatic RAW editor. Candidate scenarios such as "future load"
must be backed by separately supplied input cases and their declared assumptions. Do not silently modify loads or
ratings to manufacture a scenario.

### Run configuration and execution

| ID / priority | Change | Acceptance |
| --- | --- | --- |
| RC1 / P1 | Add a guided **Study setup** over existing XML controls: base plus full branch N-1, optional generator N-1, or supplied contingency list; selected A/B/C rating; monitored branches, areas, and kV range. Keep solver/Docker controls under Advanced. | The review screen names the exact outage and monitor scope; "all lines" appears only when the configuration truly covers them. |
| RC2 / P1 | Add a preflight diff between proposed and saved settings, validate referenced files and Docker image, and show expected output/storage implications based on prior runs or an explicit *unknown* estimate. | A reviewer sees rating, output format, input hashes, MPI count, and warnings before a new run starts; no predicted result is presented as fact. |
| RC3 / P1 | Make long runs a persistent study activity with phase/progress, current run ID, log excerpt, cancellation, and a clear failed/incomplete state. Reuse existing background jobs. | Closing the app and reopening it shows the true job status and links to the same manifest/log. |
| RC4 / P2 | Add a **method card** for every run: solver/image, configuration snapshot, selected ratings, contingency coverage, monitor filters, convergence outcomes, parser/metric versions, and source artifact paths. | An exported method card reproduces the GUI wording and can be checked against the stored manifest and XML. |

### Output analysis and metric contract

Implement the following as deterministic queries in `analysis/` and call them from both GUI and agent. Do not let
the model calculate populations from the rows that happen to fit in its context. Existing `rank_groups`,
`rank_contingencies`, `get_branch_loading`, `get_contingency_flows`, and `compare_runs` are starting points; the
shared service should consolidate their metric logic before new charts are added.

| ID / priority | Change | Acceptance |
| --- | --- | --- |
| AN1 / P0 | Define and version each metric: facility identity, line versus transformer, base versus outage, loading source, selected rating, threshold (`>=100%` by default), kV/area/monitor scope, and how unknown/null rows are handled. | Every tool result and displayed aggregate carries metric version, filters, population count, and source path. |
| AN2 / P0 | Report coverage beside findings: configured/observed events when knowable, converged/failed/unknown status, monitored facility count, and rows excluded by filters or missing data. Retain unknown when the expected event set cannot be reconstructed. | No empty table is reported as "no violations" without an observed denominator and status. |
| AN3 / P0 | Reconcile `csv_flat` percentages with the legacy TXT/Rate C proxy; identify the formula and units in each result. Mark cross-format comparison incomparable until validated against a common basis. | A format-mixed pair cannot silently yield a single improvement percentage. |
| AN4 / P1 | Expose base-case and worst-observed loading separately, plus event causing each maximum, count of recorded exceedance rows, and thermal margin in percentage points. | A selected facility opens its source event rows; negative margin is labeled as an exceedance. |
| AN5 / P2 | Add exact, server-side group counts and distribution statistics by voltage class, endpoint area, rating band, facility type, and event, with stable filters. Label area ties as belonging to both endpoints. | Group calculations use the whole eligible population; system totals are deduplicated by facility key. |
| AN6 / P2 | Build comparison over matched facility keys and comparable event sets. Show added, removed, unmatched, missing, and nonconverged items separately. | Each delta has both source run IDs and input/configuration differences; an unmatched row never becomes a zero delta. |
| AN7 / P2 | For a facility or outage, return a compact evidence bundle: rank, exact metric value, event, row count, convergence, rating basis, selected scope, and source-row locator. Reuse the event index only for requested drill-down. | A finding can be reproduced from cached reductions and, when requested, the original rows without a full CSV scan. |

The current Branch Analysis and Transformer Analysis charts summarize *recorded* maxima. P0 must decide and
document whether a new "converged-only" series can be computed for each output format. Until it can, call the
existing value "maximum among recorded rows" and show failed or unlinked events separately. Never relabel it
"maximum over all N-1 events" by assumption. Area/group means must name the underlying per-facility statistic;
"mean of each facility's maximum" differs from "maximum of area means" and from a mean of displayed rows.

### Visualization

| ID / priority | Change | Acceptance |
| --- | --- | --- |
| V1 / P1 | Extend the existing three charts with threshold line, explicit population/count labels, and a linked ranked table; keep the same filter state across cards. | Selecting an area or voltage class gives the same membership and value in chart, table, and agent query. |
| V2 / P2 | Show a distribution of facility maximum loading with bins on both sides of 100%, plus cumulative count above a selected threshold. | Hover and table expose bin boundaries, numerator, denominator, and missing-data count. |
| V3 / P2 | Show a sparse outage-by-facility matrix for top findings, with drill-down to an event or facility; virtualize or page large result sets. | The matrix never loads every flat CSV row into the GUI; a cell links to its precise event and facility. |
| V4 / P2 | Show paired-run slope/dumbbell views only for matched facilities under a comparable basis; mark new, removed, and unknown facilities in an adjacent table. | The chart cannot imply improvement from a changed rating or omitted monitor set. |
| V5 / P3 | Offer a schematic topology/area view only from validated RAW connectivity, clearly marked "schematic". A geographic map requires separately verified coordinates and is deferred. | Bus names or control-area labels are never placed at inferred geographic positions. |

### Decision dashboard and review record

| ID / priority | Change | Acceptance |
| --- | --- | --- |
| DD1 / P1 | Dashboard cards: study scope; run and convergence status; monitored facilities; facilities at/above selected rating in base and recorded outages; top outage/facility; and data gaps. | Every count names its denominator, rating, case, and link to its filtered rows. |
| DD2 / P2 | Add a finding queue with user notes and statuses such as *review*, *question sent*, *resolved by submitted evidence*, and *outside study*. Store reviewer text separately from computed facts. | Status changes never alter a metric; each finding retains run/metric version and source links. |
| DD3 / P2 | Export a frozen evidence package: study brief, methods, input/run hashes, filters, counts, charts with matching CSVs, finding notes, source-row references, and limitations. Keep original large outputs linked or optionally bundled with a size estimate. | Reopening the package reproduces every published number without asking the model; package creation records its own hash. |
| DD4 / P3 | Generate a plain-language *questions for the study author* section from concrete gaps: missing case provenance, failed events, differing rating basis, or an unstudied scenario. A reviewer edits it before export. | Each question points to an observed gap; no automated project approval or investment ranking appears. |

The dashboard is an evidence and follow-up view. It must not label a project "needed", "compliant", or
"cost-effective" from thermal utilization alone. The user's decision and any external engineering or legal
record remain outside GridLens's computed findings.

### Agent and tool architecture

| ID / priority | Change | Acceptance |
| --- | --- | --- |
| AG1 / P0 | Give the model compact, typed evidence results with field definitions and population statistics; keep paged raw rows and complete session result files for audit. Make the answer validator distinguish a citation to an aggregate from one to a limited row page. | No answer quotes a whole-population value derived from a truncated page; a cited figure can be located in its cited result. |
| AG2 / P1 | Offer regulator question starters: "What was studied?", "Which facilities exceeded ratings?", "What differs between these cases?", "What could this study not tell me?", and "Where is the evidence?" Use a consistent answer shape: finding, scope, evidence, limitation, next question. | Answers define terms on first use, cite run artifacts, and say *unknown* when evidence is absent. |
| AG3 / P2 | Grow a domain-focused MCP catalog around workflows: case inventory/validate, method/coverage, facility and event ranking, exact group aggregates, pairwise comparison, evidence retrieval, report assembly. Expose clear tool schemas and stable error remedies; use existing operations where possible. | Each question maps to a deterministic tool chain; no agent-side scan of a multi-gigabyte file is needed for standard queries. |
| AG4 / P3 | Add a durable workflow record with task steps, dependencies, inputs/hashes, idempotency keys, job/run IDs, artifact IDs, status, errors, and review checkpoints. The model proposes or selects a workflow; GridLens performs and records state transitions. | Interrupted workflows resume without duplicate runs or analysis builds, and the reviewer can see the next action and its reason. |
| AG5 / P3 | Ship three workflow templates: **explain an existing run**; **screen a submitted case** (preflight → run → build cache/index as needed → evidence dashboard); **compare two submitted cases** (validate basis → ensure both runs → compare → draft review questions). | A template can pause for missing cases or a consequential input/configuration change; routine already-authorized analysis continues in the background. |
| AG6 / P3 | Bind conversation, workflow, run selection, and evidence citations explicitly. Resuming an older conversation restores its exact scope; changing project or model is a visible new context choice. | A reviewer can continue any saved conversation and see its past plan, tool activity, and source links. |
| AG7 / P3 | Keep generated analysis code as an exceptional reviewed artifact, with recorded prompt, source, script hash, execution approval, sandbox result, and explicit unvalidated status until a deterministic query is adopted. | Standard utilization questions never require generated code; unapproved scripts do not execute. |

The agent should use one provider-independent tool and workflow contract. Hermes/Ollama remains the local first
path; the evaluated release models are **`nemotron3:33b` and `gemma4:31b`**, not Qwen. Model choice must not
change calculations. Codex and Claude adapters remain governed by [the CEII policy](../security_ceii.md);
this roadmap does not authorize hosted use, new solver connectors, or additional data egress.

The tool catalog should grow by reviewer question, with typed inputs and compact outputs. Reuse the present
project/run operations and `get_run_method`, `summarize_convergence`, `rank_groups`, `rank_contingencies`,
`get_branch_loading`, `get_contingency_flows`, and `compare_runs` where their semantics fit.

| Tool addition or extension | Inputs | Deterministic output and consumer |
| --- | --- | --- |
| `validate_case` | Project and input snapshot | RAW/XML references, counts, rating and identifier issues; intake wizard and agent preflight. |
| `get_study_scope` | Run ID | Case label, hashes, rating, monitors, configured outages, versions, known gaps; method card and every answer header. |
| `summarize_event_coverage` | Run ID and optional filter | Observed/converged/failed/unknown events and expected count only when derivable; dashboard and agent limitation text. |
| `summarize_thermal_exceedances` | Run ID, facility type, threshold, base/outage choice, filters | Exact facility and event counts with denominators and metric basis; dashboard and plain-language answers. |
| `get_evidence_bundle` | Run ID plus facility or event key | Compact finding, convergence, rating, filter, source-row locator; chart clicks, citations, and review queue. |
| `compare_study_runs` | Two run IDs, matching policy, filters | Compatibility report, matched deltas, unmatched/unknown counts, both source references; paired views and agent. |
| `assemble_evidence_package` | Saved findings and selected runs | Frozen manifest and reproducible tables/charts, with a size estimate before bundling raw outputs; export action. |

These are proposed API names, not another route to a solver. The model can choose a question-specific tool, but
the query service computes its result and the GUI presents the same record. Inputs that select a case or alter a
run require an explicit, inspectable scope; tool descriptions must never imply broader coverage than the run has.

## Architecture and migration rules

1. Put `StudyScope`, `MetricDefinition`, `Coverage`, and `EvidenceRef` in the analysis/domain layer as versioned
   records. A reference contains project, run, artifact hash/path within the project, query/filter, metric version,
   and optional facility/event key. Both the Qt view models and MCP tools call the same query methods.
2. Add optional study/case metadata without breaking existing projects. Preserve old manifests; create new
   immutable snapshots for future runs rather than rewriting a past case's meaning. Show *unknown* for absent
   legacy metadata.
3. Keep large data out of model context and top-level dashboard loads. Reuse reduced tables for counts and
   rankings; build/query the optional event index lazily for exact source rows. Store a complete result locally
   when inline output is bounded and present a direct path to it.
4. Treat each long workflow as a state machine persisted under its project. Background jobs remain the execution
   mechanism. Atomically record transitions, reconcile on restart from job/run status, and use stable request IDs
   before retrying an operation. Cancellation changes workflow state and stops only its own active jobs.
5. Preserve current CEII defaults: local files, no telemetry, loopback model endpoint, isolated generated-code
   execution, and logical tool audit. Evidence packages inherit the same local handling as run and agent exports.

## Validation and release criteria

These are proposed gates, not current test results. Record the test's rationale, method, outcome, and interpretation
for each release candidate as required by the project's testing practice.

| Gate | Method and ground truth | Required outcome |
| --- | --- | --- |
| Metric correctness | Independently calculate facility maxima, group means, thresholds, area ties, and event counts from small CSV/RAW fixtures; verify against GUI, query service, export, and agent tools. Include base, failed, missing, duplicate-key, and mixed-format cases. | Exact agreement with the reference calculations; unavailable denominators remain unknown. |
| Large-run integrity | Compare full-population aggregates with an independent streamed calculation on the supplied large run; sample source rows and contingency drill-down; measure build time, RAM, disk, and GUI responsiveness on DGX Spark. | No row-page-derived aggregate, silent truncation, stale index result, or UI freeze; document measured resource cost. |
| Comparison integrity | Pair identical and deliberately mismatched cases (rating, monitor list, event set, RAW hash, and output format). | Matched deltas reproduce reference rows; mismatches are shown and are never converted to false zeroes or benefits. |
| Workflow recovery | Terminate/reopen during run, analysis build, and answer drafting; retry and cancel; switch conversations and projects. | One workflow record, no duplicate job for the same step, recoverable status, correct prior conversation scope. |
| Regulator comprehension | Give representative nontechnical reviewers scenario, result, and limitation questions without a walkthrough; observe where terms or charts mislead them. | Reviewers can identify the studied case, denominator, and a key limitation from the first view; revise copy until observed errors are resolved. |
| Agent grounding | Run a documented set of case, method, aggregate, comparison, missing-evidence, and scope-boundary prompts on both local target models, with repeated trials. Score against independent deterministic answers and manual citation review, not model agreement. | No invented numerical, economic, capacity, compliance, or geographic claim; all cited figures resolve to the correct run and metric. Report per-model failures, not only an overall score. |
| CEII/accessibility | Review local persistence/export paths, model route and audit, keyboard navigation, chart text equivalents, and contrast. | No new unreviewed egress; equivalent numeric evidence is available without color or pointer input. |

The existing synthetic agent evaluation is a useful regression check, but its 16 scored assertions across four
questions are not a regulator acceptance test. Expand questions, cases, and independent reference results before
claiming the agent can support consequential review.

## Explicit deferrals

- No PowerWorld, PSS/E, OpenDSS, pandapower, OPF, production-cost, or market-price integration. GridPACK's
  solver and its output schema remain the source of computational evidence.
- No autonomous invention of future cases, study assumptions, engineering upgrades, or monetary benefits.
- No FERC interconnection heatmap, transfer capability or queue readiness claim from branch rating margin.
- No geographic heatmap inferred from bus names or control-area labels.
- No automated regulatory finding, compliance certification, or project approval.

These are product boundaries. A later initiative that needs those capabilities must identify its additional data,
method, domain review, and governance path before it can change the claim language above.
