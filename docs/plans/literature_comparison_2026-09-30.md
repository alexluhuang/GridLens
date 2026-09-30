# GridLens compared with the literature on LLM agents for power systems (2026-09-30)

This note compares GridLens, and in particular its planning agent Clarke, with three papers the user supplied
and with other published work found by searching journals, conference proceedings, and arXiv. For each of the
three papers it answers four questions:

1. What GridLens and the paper have in common.
2. What GridLens could take from the paper.
3. Where GridLens goes beyond the paper.
4. What further work would make GridLens a significant contribution relative to the paper.

Section 4 covers the other literature more briefly. Section 5 draws the per-paper findings into a research
agenda. Section 6 lists the weaknesses in GridLens's own evidence, which any paper about it would have to
address.

GridLens facts are taken from `main` at `6c39141`, from `docs/ARCHITECTURE.md`, `docs/clarke.md`,
`src/gridlens/agent/`, and the evaluation reports in `docs/plans/`. It extends
`docs/comparison_with_literature.md` (2026-09-22), which covered GridMind alone and predates the agent's
ability to create projects and start runs.

## 0. GridLens facts the comparison relies on

- **Solver and data.** GridPACK's contingency analysis (`ca.x`, MPI) runs in Docker with `--network none` on
  PSS/E RAW cases of versions 33 to 35. The large test case is the synthetic Texas7k case with full branch and
  generator N-1: 8,891 contingencies (8,639 converged, 252 failed), 6,823 monitored lines at 50 kV or above,
  and an 8.7 GB CSV flat result. Results are aggregated on the GPU (RAPIDS cuDF, dask-cuDF), with CPU fallbacks,
  into versioned caches, plus an optional bucketed Parquet index for drill-down into single contingencies.
- **Agent.** Clarke is one agent with one system prompt and 15 tools served over MCP (FastMCP over stdio):
  `rank`, `rank_groups`, `read_file`, `list_files`, `list_projects`, `get_project`, `get_run_configuration`,
  `get_status`, `create_project`, `start_run`, `run_analysis`, `add_project_inputs`, `configure_run`, `stop`,
  and `propose_analysis_script`. The runtime is Hermes Agent 0.21.4 driving a model served by Ollama; the
  preferred model is `nemotron-3.5-lightning` (30B total, 3B active parameters). Claude Code and Codex
  adapters exist behind the same `RuntimeAdapter` contract and are disabled by policy.
- **Local-only inference.** The endpoint must resolve to loopback; redirects and proxies are refused, cloud
  models are rejected, and the model is re-verified every turn.
- **Audit.** Every tool call gets an ID (`T1`, `T2`, ...) and paired records in an append-only
  `tool_calls.jsonl`. After each turn the controller rewrites citations that match no call, appends sources
  when the model cited none, and adds notes for truncated results, failed tools, pending changes,
  generated-script output, capacity-style questions, and sums of flows measured in different directions. For
  two question types (group means, the areas of the top lines) it replaces an unsupported answer with a
  deterministic one.
- **Human approval.** Replacing an input, rewriting an XML, or stopping running work returns a preview; the
  change is made only if the same call is repeated with `confirm=True` after the user has sent another
  message. The tool layer enforces this, not the prompt. Generated scripts run only after the user approves
  their exact SHA-256, in a read-only, network-free, capability-dropped container.
- **Provenance.** Each run copies its inputs, records their SHA-256 hashes, and stores the exact `docker run`
  command in `manifest.json`. Caches carry dataset and parser versions and are refused when stale.
- **Long work.** Runs and analysis builds started by the agent are detached jobs that survive the turn and the
  application.
- **What-if edits.** The Sensitivity Analysis tab patches loads, generators, and branches of a RAW case
  byte-for-byte. The agent cannot use it: the system prompt says "GridLens cannot edit a RAW case, change load
  or generation, or run a transfer study."
- **Evaluation.** A synthetic four-question test scores 16 criteria per model, including refusal to read an
  unselected run and refusal to answer from a stale cache. A 30-question (32-prompt) planning evaluation on
  Texas7k, with reference facts computed independently of the agent, scored gemma4:31b at 11 pass, 16
  partial, and 5 fail; after tool fixes, the 13 affected prompts went from 3/6/4 to 7/5/1. Each prompt was
  asked once, and a person scored the answers.

## 1. PowerAgent (Zhang and Xie, IEEE Power and Energy Magazine, 2025)

> Q. Zhang and L. Xie, "PowerAgent: A Road Map Toward Agentic Intelligence in Power Systems: Foundation Model,
> Model Context Protocol, and Workflow," *IEEE Power and Energy Magazine*, vol. 23, no. 5, pp. 93–101,
> Sep./Oct. 2025. doi:10.1109/MPE.2025.3579718.

**What it is.** A position paper from Harvard. It proposes three layers: domain foundation models (RAG,
fine-tuned LLMs, or transformer models trained for power-flow or state-estimation tasks), MCP as the bridge
from models to engineering software (PSS/E, PowerWorld, OpenDSS, and others), and agentic workflows with a
human in the loop. It announces the open-source PowerAgent community with three repositories: PowerFM
(models), PowerMCP (MCP servers), and PowerWF (workflows). Its two use cases are a RAG data-center siting
assistant and a load-growth study in which the LLM picks a workflow, runs contingency analyses for several
load-growth scenarios through MCP, and asks for permission before running simulations and before sending the
report. It reports no implementation measurements or evaluation. PowerMCP now has servers for 15 packages
(PowerWorld, PSS/E, OpenDSS, pandapower, PyPSA, ANDES, Egret, PSLF, PowerFactory, PSCAD, LTspice, GenX, HOPE,
surge, PLEXOS); GridPACK is not among them, and its documentation describes path restrictions but no approval
workflow or audit log.

### 1.1 What GridLens shares with PowerAgent

- **MCP as the tool interface.** GridLens serves its tools over MCP with the official SDK, as PowerAgent
  recommends, and any MCP-capable runtime could use them.
- **The model calls trusted engineering software.** PowerAgent's main safety argument is that the agent
  should run PSS/E or PowerWorld instead of computing power flows itself. GridLens applies the same rule to
  GridPACK and to its own deterministic analysis code.
- **Copilot, not autopilot.** Both treat the agent as an assistant that does repetitive work while an engineer
  stays in charge, and both put approvals before consequential steps.
- **The load-growth workflow.** PowerAgent's Figure 4(b) (select a workflow, run contingency cases, format the
  result, and get approval before delivery) closely matches what Clarke does now: `create_project`,
  `configure_run`, `start_run`, `run_analysis`, then `rank` and a cited draft. Clarke still cannot build the
  load-growth scenarios itself (Section 1.2).
- **Domain knowledge matters more than model size.** PowerAgent says effective agents need knowledge of
  planning practice and regulation. Clarke's system prompt encodes that kind of knowledge: thermal margin is
  not transfer capability, maximum loading includes the base case, GridPACK's violation flag is not an
  overload count, and flows summed across ties in different directions are not an interface flow.
- **Open source.** GridLens is GPL-3.0.

### 1.2 What GridLens could take from PowerAgent

1. **An explicit workflow layer.** In PowerAgent the LLM selects a predefined workflow instead of improvising
   the tool chain. GridLens's roadmap (AG4, AG5 in `regulator_workbench_roadmap.md`) already plans workflow
   templates as persisted state machines. PowerAgent adds two points: approval nodes should be configurable
   per step ("human approval can be set at any critical step"), and report delivery should be a step with
   its own approval. Implement "screen a submitted case", "compare two cases", and "load-growth sweep" as
   deterministic workflows whose steps are GridLens tool calls, whose state is on disk, and whose approval
   points are data, not prompt text.
2. **A configurable approval policy.** GridLens gates three destructive actions. `start_run` with overrides of
   the image, pull policy, memory limit, or extra Docker arguments is not gated, which the architecture document
   lists as a known exposure. A policy table keyed by tool and argument (for example, any Docker override or
   non-`never` pull policy requires confirmation) would follow PowerAgent's settable approvals and close that
   exposure.
3. **Load-growth scenarios through the agent.** Expose the surgical RAW patcher (`psse/patch.py`) as agent
   tools: scale load by area or zone, take a branch out of service, change a generator's output. Each edit
   would write a new case with `sensitivity_changes.json`, as the Sensitivity tab does, and would need
   confirmation. That makes PowerAgent's use case 2 runnable end to end on GridPACK.
4. **The foundation-model layer.** Two cheap steps fit GridLens's local-only rule. First, retrieval over
   public planning documents (NERC TPL-001, regional planning criteria, GridPACK manuals) with a local
   embedding model, so Clarke can quote a criterion with its section number while still declining to make
   a compliance finding. Second, fine-tuning a small local model (LoRA) on GridLens's audited tool traces,
   which the session folders already record. The PowerAgent authors' own scaling study (Liu et al., 2025,
   arXiv:2503.20040) reports that modest fine-tuning suffices for multi-task energy-system work.
5. **Joining the ecosystem.** Publish GridLens's tools as a PowerMCP-compatible server for GridPACK. That
   would be PowerMCP's first HPC contingency-analysis backend. MCP's resource and prompt primitives also fit
   GridLens: run manifests and evidence records as resources, and workflow templates as prompts.

### 1.3 Where GridLens goes beyond PowerAgent

- **It is built and measured.** PowerAgent is a road map with two illustrations and no measurements. GridLens
  is a working system with 357 test functions, an MCP conformance test against the frozen executable, and a
  scored 30-question evaluation on a 7,000-bus synthetic case.
- **Human approval is enforced in code.** PowerAgent says the LLM "may ask the user for approval." In GridLens
  the tool refuses to act until the user has sent a later message, so a model cannot approve its own change,
  and a prompt injection cannot either. That is a stronger guarantee than approval the model is asked to
  request.
- **The security layer is concrete.** PowerAgent names cybersecurity as a box in its top layer. GridLens
  implements loopback-only inference checked every turn, a hosted-runtime gate, a network-free solver
  container, a hardened sandbox for generated code, per-session path scoping that refuses symlinks, `0600`
  session files, and handling of tool output, log lines, and bus names as untrusted data.
- **It runs on local models.** PowerAgent's examples use GPT-4o and look to fast hosted models for latency.
  GridLens shows the architecture working with open-weight models of 3B to 31B active parameters on one DGX
  Spark, which answers the barriers PowerAgent itself names: data sharing, security, and cost.
- **Provenance.** PowerAgent does not discuss how an answer is traced to its source. GridLens has call IDs,
  citation rewriting, input hashes, and the exact solver command for every run.
- **Output volume.** PowerAgent does not address results larger than a model's context. GridLens keeps
  multi-gigabyte results out of the model, computes rankings and statistics over every row, reports
  `total_matching` and `objects_used`, and saves complete results to files when they are too large to return.
- **Long workflows.** GridLens's background jobs outlive the turn; PowerAgent does not consider runs that take
  longer than a conversation.

### 1.4 How GridLens could become a contribution relative to PowerAgent

- **Measure PowerAgent's claims.** PowerAgent asserts productivity gains with a human in the loop but measures
  none. A study with transmission planners or regulatory staff, doing the load-growth study with and without
  Clarke, measuring time, errors caught, errors introduced, and the number of approvals needed, would be the
  first such measurement for an MCP-based power agent.
- **Contribute the GridPACK MCP server and a trust contract.** A GridPACK server in PowerMCP, together with a
  written contract for safety-critical MCP tools (a read, write, or destructive effect class per tool;
  confirmation across turns; audited call IDs; untrusted-output handling), would turn PowerAgent's MCP layer
  from a pattern into a specification that others can test against.

## 2. X-GridAgent (Wen and Chen, arXiv 2025)

> Y. Wen and X. Chen, "X-GridAgent: An LLM-Powered Agentic AI System for Assisting Power Grid Analysis,"
> arXiv:2512.20789 [eess.SY], Dec. 2025.

**What it is.** A Texas A&M system with three layers. A planning layer decomposes a query into a sequence of
(server, objective) tasks. A coordination layer routes each task and keeps a short-term memory of
intermediate results. An action layer picks tools within a server and runs a reflection loop that asks the
LLM whether the task is done. Eight MCP servers are built on pandapower: Retrieval, PowerFlow, OPF,
Contingency, ShortCircuit (IEC 60909), Topology, Edit, and Plot. There are two algorithmic contributions:
LLM-driven prompt refinement, in which a judge agent compares outputs with expert reference answers and an
edit agent rewrites the system prompt, with human correction; and schema-adaptive hybrid RAG, in which an LLM
selects the tables and columns relevant to a query, the rows are sorted by the key column, and a weighted
BM25 and dense retriever picks the top chunks. The system uses the GPT-5 API, a PySide6 GUI, IEEE 39, 118, and
300-bus cases and the Texas 2k synthetic grid, and a document store of ERCOT planning and operating guides.
It was evaluated on 11 queries, each run 30 times at temperature 0, with a reported 100% success rate against
manually computed answers.

### 2.1 What GridLens shares with X-GridAgent

- **MCP tool servers and a deterministic solver** for every number.
- **A PySide6 desktop application** with a chat panel.
- **N-1 contingency analysis on Texas synthetic grids**: Texas 2k in X-GridAgent, Texas7k in GridLens.
- **Chained multi-step studies.** X-GridAgent's Q9 (power flow, then the top five lines, then their
  contingencies) has the same shape as Clarke's create, configure, run, analyze, and rank sequence.
- **The structured-data problem.** Both papers recognize that flattening large result tables into text
  chunks fails. X-GridAgent answers with schema selection and sorting before retrieval. GridLens answers with
  query tools (`rank`, `rank_groups`, `read_file` with filters, group-by, and joins) that compute in code.
- **Prompt refinement against reference answers.** GridLens did this by hand: it evaluated against reference
  facts, fixed tool descriptions and prompt text (the exact `thermal_margin_pct_points` argument, tie-line
  guidance), and ran again. X-GridAgent automates the loop.
- **Case edits.** X-GridAgent's Edit server corresponds to GridLens's RAW patcher, which only the GUI can use
  (Section 0).

### 2.2 What GridLens could take from X-GridAgent

1. **Repeated trials with pinned decoding.** X-GridAgent ran every query 30 times at temperature 0. GridLens
   asks each question once and sets no temperature or seed in the Hermes profile. Pin decoding parameters
   for evaluations, run each prompt k times, and report pass@k and pass^k, the probability that all k attempts
   pass (from τ-bench), per question and per model.
2. **An automated refinement loop, with deterministic checks first.** GridLens already has the inputs
   X-GridAgent's loop needs: questions, reference facts, a rubric, and audited calls. Add a local judge model
   that pre-scores prose criteria (caveats, plain language) and an edit agent that proposes diffs to the prompt
   and tool descriptions, with a person approving each diff and the full evaluation re-run as a regression
   gate. Keep numbers, citations, and confirmations scored deterministically. X-GridAgent's own Figure 3 shows
   its judge missing that an answer did not name the contingency behind a voltage violation; only the human
   caught it.
3. **Document retrieval with section citations.** X-GridAgent's Q2 answers from the ERCOT Nodal Operating
   Guides and cites the section and paragraph. A local retrieval tool over public standards (NERC TPL-001-5.1,
   FERC Order 2023 materials, regional planning criteria, GridPACK documentation), using BM25 plus a local
   embedding model, would let Clarke state which rating and criterion a planning study normally applies. Its
   results would carry call IDs like any other tool.
4. **Topology queries.** A Topology tool built on the RAW metadata (neighbors of a bus, the lines within n
   buses of a facility, paths between areas, and which outages island which buses) would answer questions
   the 30-question evaluation shows are awkward today. Question 8, "which outages island part of the system",
   took 430 seconds and listed 69 of 82 outages.
5. **A plot tool.** Clarke cannot produce a chart, although the analysis tabs can. A deterministic plot tool
   (loading distribution, per-area bars, top-N facilities, a comparison of two runs), saved as a session
   artifact with a call ID, would make answers match the GUI's figures.
6. **The Edit server's role, done safely.** X-GridAgent's Q10 compares a base case, a line outage, and doubled
   load. Exposing the RAW patcher (Section 1.2, item 3) gives Clarke the same ability, with byte-preserving
   edits, confirmation, and a recorded change list.
7. **A visible plan.** X-GridAgent shows its generated plan in the GUI before results. For multi-step studies
   Clarke could show the plan, and the user could approve it once, instead of approving individual steps.
8. **In-loop checking.** X-GridAgent's reflection step checks completion inside the loop. GridLens's checks run
   after the turn and can only append notes. Offering the checks as a tool the model must call before it
   answers (for example `check_answer`, which runs the citation, truncation, scope, and caveat checks) would
   let the model fix the answer itself, and GridLens would still run the checks afterwards.

### 2.3 Where GridLens goes beyond X-GridAgent

- **CEII compatibility.** X-GridAgent sends queries and tool results to the OpenAI API, which rules it out for
  real utility cases under CEII handling rules. GridLens keeps inference on the machine and enforces it.
- **Exact answers about whole populations.** X-GridAgent's Retrieval server finds the "top 30 lines" by
  selecting columns, sorting, and retrieving the top-k chunks by relevance. It can return the right rows, but
  it cannot compute a count, mean, or distribution over thousands of rows, and nothing tells the user when a
  chunk was missed. GridLens's `rank_groups` computes each statistic from every object in scope and reports how
  many it used, `rank` reports `total_matching`, and the controller discloses truncation. The GridLens
  evaluation found the failure mode directly: a model that averaged the ten rows it could see.
- **Scale.** X-GridAgent runs one power flow on Texas 2k (3,992 lines), and its contingency tool runs one
  outage per call; its Q9 made three calls for three lines. GridLens runs a full N-1 of 8,891 contingencies
  in parallel with MPI, aggregates 8.7 GB of results on the GPU, and indexes them for drill-down. A full N-1
  on a 7,000-bus case through per-outage calls in an agent loop would not be practical.
- **Industry case format.** GridLens reads and edits PSS/E RAW versions 33 to 35. X-GridAgent loads cases from
  pandapower's built-in library.
- **Audit and citation enforcement.** X-GridAgent has no call-level audit or check that citations resolve; its
  outputs were checked by hand. GridLens records every call, rewrites unresolvable citations, and stores input
  hashes and solver commands.
- **Safe writes.** X-GridAgent's Edit server changes the network with no confirmation step described. GridLens
  never changes a run's inputs, copies and hashes them, and holds destructive changes for a later turn.
- **Tests of failure behavior.** X-GridAgent's 11 queries test the successful path. GridLens's tests include
  refusing to read an unselected run, refusing to answer from a stale cache, holding an XML change for
  confirmation, handling a failed run and a run with no analysis, stating scope and caveats, and writing for a
  reader who does not know GridLens.
- **Long runs, and code only after review.** GridLens has detached jobs and a sandbox for generated code;
  X-GridAgent runs synchronously and generates no code.
- **Caveats about domain meaning.** X-GridAgent reports solver outputs as they are. Clarke must state the
  metric, rating basis, and convergence coverage, and the controller adds the capacity and flow-direction
  notes when they apply.

The two evaluations cannot be compared by score. X-GridAgent reports 100% on 11 mostly single-step queries
with a frontier model at temperature 0. GridLens reports 11 of 32 passing on harder questions with a local
31B model. GridLens's advantage is in what its evaluation tests, not in its pass rate.

### 2.4 How GridLens could become a contribution relative to X-GridAgent

- **Retrieval against query tools, measured.** Build both approaches over the same GridPACK results (a
  schema-adaptive hybrid RAG retriever, and GridLens's `rank` and `rank_groups`), and ask the same questions
  of the same local models. Measure numeric accuracy, completeness on whole-population questions (counts,
  means, per-area totals), citation validity, and cost. X-GridAgent claims its RAG solves the structured-data
  problem; a controlled comparison on a 7,000-bus N-1 would test that claim.
- **Hierarchy against a single agent, measured.** X-GridAgent asserts that the planning, coordination, and
  action layers improve flexibility, but reports no ablation. Running GridLens's question set with a
  single agent and with a planner-and-coordinator wrapper over the same tools would answer that question
  for the power domain.

## 3. GridMind (Jin, Kim, and Kwon, SC Workshops '25)

> H. Jin, K. Kim, and J. Kwon, "GridMind: LLMs-Powered Agents for Power System Analysis and Operations," in
> *Proc. SC Workshops '25*, ACM, 2025, pp. 560–568. doi:10.1145/3731599.3767409. arXiv:2509.02494.

**What it is.** An Argonne prototype with an ACOPF agent (`solve_acopf_case`, `modify_bus_load`,
`get_network_status`), a contingency agent (`solve_base_case`, `run_n1_contingency_analysis`,
`analyze_specific_contingency`, `get_contingency_status`), and a planner and coordinator described without
prompts or evaluation. Built with PydanticAI and pandapower. Agents share typed state (`ACOPFSolution`,
`ContingencyAnalysisResult`, `AgentContext`, `WorkflowState`), a chronological log of edits, and a cache
keyed by case, outage, and a hash of the edits. Results are validated for convergence and power balance
(mismatch below 1e-4 p.u.), and the paper describes, but does not measure, automatic recovery. The LLM ranks
critical elements from solver outputs. Six hosted models were tested on IEEE cases: all solved ACOPF on case118
in five runs, and on the contingency ranking five models agreed on the top five lines while GPT-5 Mini reported
a different set and 165% maximum overload instead of 137%.

### 3.1 What GridLens shares with GridMind

- **The same principle.** The model plans and explains; deterministic code computes. Both prompts forbid
  invented numbers, although GridMind's published prompt omits the rule its text quotes.
- **N-1 contingency analysis with ranking** of critical outages and facilities.
- **The goal that every number maps to a stored tool output.**
- **Several models under one prompt and tool set.** GridMind tested six hosted models. GridLens's
  installed-model test gives every local model the same prompt and tools; recorded results cover two,
  gemma4:31b and nemotron3:33b, which scored 16 of 16 criteria each.
- **Persistent sessions** that can be resumed.
- **Validation of solver output.** GridMind checks convergence and power balance. GridLens counts converged and
  failed contingencies by status code, reports coverage, and refuses stale caches.
- **Freshness of cached results.** GridMind keys its cache by an edit hash; GridLens versions caches and
  compares file times and sizes.
- **What-if edits.** GridMind's `modify_bus_load` corresponds to the Sensitivity tab, which the agent cannot use.
- **Small models are enough.** GridMind found smaller models as accurate as larger ones with tools. GridLens's
  preferred model has 3B active parameters.

### 3.2 What GridLens could take from GridMind

1. **Typed output schemas.** Every GridLens tool returns a plain dictionary, and the MCP server is registered
   with `structured_output=False`, so the model learns field names only after a call. A TypedDict or Pydantic
   model per tool would let MCP publish output schemas and return `structuredContent`, let tests catch changes
   in row shape, and give a claim checker (Section 5) exact fields to match against.
2. **An edit log with an edit hash.** When the RAW patcher is exposed to the agent, key each sensitivity run by
   the base case's hash and a hash of its normalized change list. `sensitivity_changes.json` already records the
   changes. With that key, Clarke can tell whether a run for a given scenario already exists and reuse it, and
   comparisons can state exactly which edits separate two runs.
3. **Structured workflow state.** GridMind's `WorkflowState` (a plan and the completion of each step) is the
   in-memory form of the workflow record in GridLens's roadmap (AG4). GridLens should persist it to disk, as the
   roadmap says, so a study survives a restart.
4. **Voltage criteria.** GridMind's contingency agent treats voltage below 0.94 p.u. as a violation. GridLens's
   compact caches hold loading, not bus voltages; the drill-down index has voltages only at the ends of
   monitored branches. Adding each contingency's minimum and maximum bus voltage, and a count of buses outside
   limits, to `contingency_summary` would allow voltage screening without the index.
5. **A deterministic severity index.** GridMind ranks criticality by LLM judgment, which is why its models
   disagreed. The classical alternative is a performance index for contingency screening, a weighted sum of
   (flow/limit)^2n over branches plus a voltage term (Ejebe and Wollenberg, *IEEE Trans. PAS*, 1979; GridMind
   cites it). Implementing it as a named, documented `rank` metric would give GridLens a combined thermal and
   voltage criticality that every model reports identically.
6. **Run validation beyond convergence.** Preparing GridLens's evaluation found a case that overloaded the
   slack generator and left a flat result with only the base case. A `validate_run` check (convergence rate,
   slack output against its limits, islanding count, facilities with no rating) would catch that before
   anyone reads the results. The roadmap's `validate_case` covers the input side.
7. **Latency and token accounting.** GridMind reports latency per model. GridLens writes `usage.json` per
   session but does not report it; the evaluation report should give time and tokens per question and model.
8. **Recovery as a proposal.** GridMind retries with changed solver settings automatically. GridLens should
   propose a retry, for example a different solver tolerance or MPI count, as a change the user confirms.

### 3.3 Where GridLens goes beyond GridMind

- **Auditability is enforced, not asserted.** GridMind says every number maps to a stored output but shows no
  mechanism. GridLens gives every call an ID, rewrites citations that match no call, and cites the turn's sources
  when the model cites none.
- **Rankings are deterministic.** `rank` sorts by a named metric in code, so every model receives the same
  ranking. GridMind's Table 1 shows the variation this avoids.
- **Evaluation of failure behavior**, with reference facts computed independently of the agent.
- **Local-only inference.** GridMind called OpenAI, Anthropic, and Argonne's Argo proxy.
- **Scale.** GridMind's largest case is IEEE 300. GridLens runs full N-1 on 7,000 buses with GridPACK's MPI
  solver and aggregates 8.7 GB of results on the GPU.
- **Industry inputs.** PSS/E RAW versions 33 to 35 instead of pandapower's IEEE cases.
- **Governance.** Confirmation across turns, a sandbox for generated code, and path scoping. GridMind does not
  discuss data governance.
- **Operation.** Background jobs, run manifests with input hashes, and plain-language answers for regulators.

### 3.4 How GridLens could become a contribution relative to GridMind

- **Rerun GridMind's contingency experiment.** Run full N-1 on IEEE 118 in GridPACK, ask several local models
  for the five most critical lines ten times each, and report the variance, which should be zero by
  construction, next to GridMind's Table 1. Then report the rate at which answers state numbers that appear in
  no cited result. GridMind asserts that rate is zero; nobody has measured it.
- **Move from one case to a study.** GridMind works on one case with in-memory edits. A multi-case study
  (seasonal cases, a load-growth series, a before-and-after upgrade pair) with durable lineage between runs
  would address the planning workflow, which GridMind's operational framing does not.

## 4. Other literature

*(Section filled in from the literature search; see below.)*

## 5. What would make GridLens a significant contribution

*(See below.)*

## 6. Weaknesses in GridLens's own evidence

*(See below.)*
