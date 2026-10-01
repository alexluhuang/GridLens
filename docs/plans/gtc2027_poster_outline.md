# GTC 2027 poster outline: GridLens

Status: outline, 2026-09-30. Every figure below comes from a file in this repository or a run on this
machine, and its source is given beside it. Figures marked **[measure]** do not exist yet; section 9 says how
to produce each one before the poster is printed.

## 1. What the poster has to do

### 1.1 The examples

Both winners share one shape, and the poster should follow it.

| | GTC 2026 winner (Wiwynn, data-extraction agent) | GTC 2025 winner (SBTC, battery disassembly) |
|---|---|---|
| Format | Landscape, 43 × 24 in (3096 × 1728 pt), four columns | Landscape, three columns |
| Title block | Title in two lines, then one line of numbers: "6x Faster Component Processing. 100% Accuracy" | Title in two lines, authors and email |
| Order | 1 Objective, 2 Challenges, 3 Our Solution (3.1 to 3.3), 4 Key Achievements, References | Motivation, Challenges, Contributions, method sections, Results, References |
| Text | About 510 words, all bullets, no paragraph longer than two lines | About 450 words, bullets |
| Visuals | One pipeline diagram, one deployment diagram, two annotated screenshots, one before/after example | Photos, pipeline diagram, simulation renders |
| Numbers | Four headline results in the last column | Three results in one box |

Lessons to keep: a numbered path the eye can follow; one line of hard numbers under the title; diagrams
that carry the method; results as a short list of measured outcomes.

Lessons to avoid: the 2026 winner is covered in vendor logos and product boxes. Our rules forbid NVIDIA
branding (1.2), so NVIDIA technologies are named in text only.

### 1.2 Rules, and how this outline meets them

| Rule | How the poster meets it |
|---|---|
| Real-world impact, with metrics and a case study | Section 3.1 frames the regulator's problem with public plan figures; Panel 6 is a case study of one review session on a public synthetic grid, with times and answers. |
| Technical innovation | Panel 4 (architecture) and Panel 7 (what no published system combines). Kept secondary to the use case, as asked. |
| Problem, NVIDIA technology, benchmarking methods, results | Panels 1–2, 5, 8, and 6–7. |
| Technical depth, acronyms explained | A glossary strip in Panel 2 defines N-1, CEII, RAW, and thermal utilization. |
| Visually clear | Four columns, seven visuals, one palette (1.4), fonts in 1.4. |
| Cite relevant work | Panel 10, with the three supplied papers, the closest published analogs, and the tools used. |
| No product promotion, no marketing language | GridLens is presented as a research system with measured behavior. No "download now", no pricing, no superlatives. The one priority claim is qualified: "to our knowledge", with Table 7 as its evidence. Banned words list in 1.3. |
| No proprietary or confidential information | Only public synthetic grids (TAMU Texas7k) and public documents (CAISO, DOE, NERC). No CEII, no real utility case, no screenshot of a real project. The WECC study in 3.1 is cited only if it is public by March 2027. |
| No NVIDIA branding | No NVIDIA logos, no NVIDIA green (#76B900) anywhere, no product badges or trademark marks. Hardware and libraries are named in plain text in Panels 5 and 8, as the methods require. |

### 1.3 Wording rules for every panel

- Say what was measured, on what, and how. Replace any adjective with the number behind it.
- Do not use: revolutionary, cutting-edge, state-of-the-art, industry-leading, seamless, powerful, game-changing,
  unlock, empower, next-generation, world-class, best-in-class, transform.
- "First" appears once, qualified: "To our knowledge, the first ... (Table 7)".
- "100% local" becomes a definition the reader can check: "All computation and inference run on one
  workstation. No project data leaves it." The only network traffic is the one-time, user-approved download
  of the agent runtime and model.
- Say "thermal loading" and "rating exceedance", not "congestion", which many regulators read as market
  congestion cost (roadmap, "Scope and vocabulary").

### 1.4 Visual system

- Canvas 43 × 24 in landscape (the 2026 winner's size); check the GTC 2027 template when it is published.
- Four columns of equal width; a title band about 3.5 in tall.
- Fonts: one sans-serif family. Title 96–110 pt, subtitle 48 pt, panel headers 48–54 pt, body 28–32 pt,
  captions 22–24 pt. Nothing under 22 pt.
- Palette: deep navy (headers and diagrams), slate grey (text and boxes), one amber accent for the numbers
  that matter, and a colorblind-safe blue/orange pair for charts. No green, to stay clear of NVIDIA branding.
- Every chart has a one-line takeaway above it and its source below it.
- Word budget: about 600 words of body text, near the winners' 450–510.

## 2. Positioning

**The claim, as the poster states it:** To our knowledge, GridLens is the first fully local, open-source,
agentic AI system for transmission utilization review built for grid regulators.

Each word is backed on the poster:

- **Fully local:** Panel 5; the model endpoint is checked to be loopback every turn, and the solver container
  runs with `--network none` (`docs/ARCHITECTURE.md` §7).
- **Open-source:** GPL-3.0 code, GridPACK (BSD-style, PNNL), Hermes Agent and Ollama (open source), and
  open-weight models (Panel 8). **[verify each license before print]**
- **Agentic:** the agent sets up projects, runs N-1 studies and edited-case studies, builds analyses, and
  answers from 18 audited tools (Panel 4).
- **For regulators:** the questions, vocabulary, and guardrails come from a regulator's review of a filed
  study (Panels 1–2), not from an operator's or a planner's workflow.
- **"First":** Table 7 compares published systems on intended user, inference location, code availability,
  solver, and scale. None of them targets regulators; the closest local, governed system (Mylonas et al.,
  2026) serves a TSO control room on a 35-bus model.

The poster leads with the use (who, which question, what they get) and keeps the technical distinctions to
one panel (7), as agreed.

## 3. Title block

**Title options** (pick one; no product-style tagline):

1. GridLens: A Local, Open-Source AI Agent for Transmission Utilization Review by Grid Regulators
2. Letting Regulators Check the N-1 Studies Behind Transmission Plans: A Local, Open-Source Agentic Workbench
3. Regulator-Run N-1 Studies on One Workstation, With Every Number Cited

**Numbers line** (the 2026 winner's strongest device). Use only figures that are measured by print time:

> 8,891-contingency N-1 study of a 6,717-bus grid in under 4 minutes · Plain-language answers cited to
> their source · No data leaves the workstation

- 8,891 contingencies, 6,717 buses: sample run `2026-07-28_14-46-26`, convergence CSV and RAW case.
- Under 4 minutes: that run took 227 s from manifest to completion (`manifest.json` `created_at`,
  `status.json` `updated_at`), 20 MPI ranks.
- Replace or add an answer-time figure only after the evaluation re-run (9.3). The three live answers
  measured so far took 21, 41, and 61 s, which is too few to headline.

**Authors and affiliations:** [names], [affiliation], contact email. Repository URL and QR code go in
References, not in the title band.

## 4. Layout

```text
+-------------------------------------------------------------------------------------------+
|  TITLE (2 lines)                                                   authors, affiliation   |
|  numbers line                                                                             |
+----------------------+----------------------+----------------------+----------------------+
| 1 The review gap     | 4 How GridLens works | 6 Case study: one    | 8 Benchmarking       |
|   (problem)          |   [V2 architecture]  |   review session     |   methods            |
|   [V1 gap graphic]   |                      |   [V4 storyboard]    |   (table)            |
+----------------------+                      |                      +----------------------+
| 2 Goal and scope     |                      |                      | 9 Results            |
|   + glossary strip   +----------------------+----------------------+   [V5 validation]    |
|                      | 5 NVIDIA technology  | 7 What no published  |   [V6 eval bars]     |
+----------------------+   on one workstation |   system combines    |   [V7 time split]    |
| 3 Trust controls     |   [V3 resource map]  |   [Table 7]          +----------------------+
|   for regulators     |                      |                      | 10 Limits, next      |
|                      |                      |                      |    steps, references |
+----------------------+----------------------+----------------------+----------------------+
```

Reading order follows the numbers: problem and goal (column 1), system and hardware (column 2), use and
distinctiveness (column 3), evidence (column 4). The case study sits in the center, where visitors stop.

## 5. Panel by panel

Each panel gives its purpose, a word budget, draft text in the voice the poster should use, its visual, and
the source of every number.

### Panel 1. The review gap (problem statement)

*Purpose:* show a real problem with public numbers. About 90 words, plus V1.

Draft text:

- Regulators approve transmission plans on the strength of utility-run N-1 studies. CAISO's 2025–2026 plan
  recommends 33 reliability-driven projects totaling $4.2 billion, out of $6.7 billion in all [CAISO 2026].
  MISO approved $21.8 billion in one portfolio [DOE 2026].
- The studies behind these figures run in licensed tools, on network models that are Critical Energy/Electric
  Infrastructure Information (CEII), by teams of power-system engineers.
- Regulatory staff rarely have the tools, the engineers, or the permission to rerun and question those studies,
  and CEII rules keep the models away from cloud AI services.

V1, "the review gap": two lanes. The utility's lane: model, licensed solver, engineers, filed study. The
regulator's lane: the filing, a question, and no way to check it. GridLens as the bridge on the regulator's
side, drawn inside a box marked "one workstation, offline". Simple line icons; no logos.

Optional motivating result, if public by March 2027: a full-AC, exhaustive N-1 study of the Western
Interconnection found mean N-1 utilization of 23.5% across 15,034 monitored facilities, with stress
concentrated in a few, mostly transformers [Prabha et al.]. This is the kind of question GridLens lets a
regulator ask of any filed case. **[confirm publication status; cite only if public]**

Sources: `~/Downloads/caiso_updated-board-approved-2025-2026-transmission-plan.pdf` (Executive Summary);
`~/Downloads/Exec_sum_National Transmission Needs Study Draft ... July 2026.pdf`;
`~/Downloads/Comm_Eng_WECC_Utilization.pdf`.

### Panel 2. Goal and scope

*Purpose:* say exactly what GridLens is for, in the regulator's words. About 80 words, plus a glossary strip.

Draft text: *Goal:* let a regulator's staff rerun a filed transmission study on their own workstation and ask
it, in plain language:

1. What was studied, with which inputs and settings?
2. Which facilities exceed their thermal ratings, under which outage?
3. How complete is the evidence: which contingencies failed or islanded?
4. What changes if load grows, or a line is out?
5. What should we ask the study's author next?

*Out of scope, by design:* transfer capability, market congestion cost, compliance findings, and project
approval. GridLens reports thermal loading in a supplied case and says what else a finding would need.

The five questions come from the reviewer journeys in `docs/plans/regulator_workbench_roadmap.md`; the
scope boundary from its "Outside this data boundary" list.

Glossary strip (one line each): **N-1**, the loss of any single element; **thermal utilization**, flow as a
percentage of a facility's rating; **CEII**, Critical Energy/Electric Infrastructure Information, which may
not be shared; **PSS/E RAW**, the industry text format for a network case; **GridPACK**, PNNL's open-source
parallel power-system solver.

### Panel 3. Trust controls for regulators

*Purpose:* show why a regulator can rely on the answers. This is where the regulator focus becomes design.
About 80 words, as a two-column list of control and what it prevents.

| Control | What it prevents |
|---|---|
| Every number comes from a deterministic tool call, and every answer cites the call (`[T3]`); a citation that matches no call is marked invalid | Numbers invented by the model |
| Rankings and statistics are computed over every row, with the count used | A "top 10" read as the whole system |
| Changes to inputs, the XML, a running job, or the case wait for the user's next message | A model approving its own change |
| Model-written scripts run only after a person approves their exact hash, in a network-free sandbox | Unreviewed code |
| Every run records input hashes and the exact solver command | Unreproducible results |
| Answers state metric, rating basis, and coverage; thermal margin is never presented as transfer capability | Overreading a screening result |

Source for each: `docs/ARCHITECTURE.md` §2.6 decisions 7, 9–12, and §3.2.7.

### Panel 4. How GridLens works (the system)

*Purpose:* the architecture, as one diagram. About 60 words, plus V2.

Draft caption: A desktop application runs GridPACK's contingency analysis in a network-free container, reduces
its multi-gigabyte output on the GPU, and exposes 18 audited tools to a local language model over the Model
Context Protocol (MCP). The model plans and explains; the tools compute.

V2, architecture (left to right):

1. Inputs: PSS/E RAW case (v33–35), GridPACK XML.
2. Run: GridPACK `ca.x` with MPI, in Docker with `--network none`, or an edited copy of the case for what-if
   studies.
3. Reduce: result CSV (8.7 GB, 74.7 M rows) to compact tables on the GPU with RAPIDS cuDF, and to a Parquet
   index on the CPU with PyArrow.
4. Ask: the agent (Hermes Agent runtime, local model served by Ollama) calls tools over MCP. Tool groups:
   rank and aggregate results; read any project file; network topology; search reference documents; set up,
   run, and edit studies.
5. Answer: plain-language findings with call-ID citations, an audit log, and a readable conversation record.

A dashed boundary around everything, labelled "one workstation, no network access for data". The trust
controls from Panel 3 as small shield marks on the arrows they guard.

Source: `docs/ARCHITECTURE.md` §2.1–2.4 and §3.2.7 (tool table).

### Panel 5. Application of NVIDIA technology

*Purpose:* the required section: exactly how NVIDIA hardware and software enable the work. About 90 words,
plus V3. Names in plain text, no logos.

Draft text:

- **One DGX Spark runs the whole study.** Its GB10 superchip's 20 Arm cores run GridPACK's 20 MPI ranks, and
  its Blackwell GPU runs both the result reduction and the language model. The 128 GB of unified memory holds
  an 8.7 GB result file and a 25 GB model at once, so no data moves between machines.
- **RAPIDS cuDF (CUDA 13)** reduces the 8.7 GB result file to per-facility and per-contingency summaries on
  the GPU in 13 s, 10 times faster than Dask on all 20 CPU cores (132 s), with identical maximum loadings.
  CPU paths remain as fallbacks.
- **Local inference on the GPU:** the preferred model, NVIDIA Nemotron 3.5 Lightning (30B parameters, 3B
  active per token, 1M-token context), is served by Ollama on loopback.
- **Next:** a GridPACK build with NVIDIA cuDSS for the contingency power flows. **[measure, 9.2; show only if
  measured with GPU access]**

V3, resource map: a single box for the DGX Spark split into CPU cores, GPU, and unified memory. Arrows show
which stage uses each (GridPACK on the cores; cuDF and the LLM on the GPU; the result file, the Parquet
index, and the model weights in unified memory). Annotate each with its measured time or size: GridPACK
227 s on 20 cores; cuDF reduction 13 s with a peak of 23 GB of unified memory; result file 8.7 GB; model
25 GB.

Sources: this machine (`nvidia-smi`: NVIDIA GB10, driver 580.178.04; `lscpu`: 10 Cortex-X925 and 10
Cortex-A725 cores; `/etc/dgx-release`: DGX OS 7.2.3; `free`: 121 GiB visible of 128 GB); `pip list`:
cudf-cu13 26.6.0, dask-cudf-cu13 26.6.0; `docs/clarke.md` model table; reduction timings from 9.1.

Note for the author: lead with the 10 times against Dask on 20 cores, the strongest CPU path. GridLens's
single-threaded Python fallback took 20.5 min (95 times slower than cuDF), but a reader will call it a weak
baseline. Do not claim dask-cuDF speed: on this file it was slower than CPU Dask (9.1).

Note for the author: the solver run of 2026-09-23 used the cuDSS image, but its log says "The NVIDIA Driver
was not detected. GPU functionality will not be available", because GridLens starts the solver container
without `--gpus`. That run used the image's PETSc/KLU fallback. Do not attribute its 97 s to the GPU.

### Panel 6. Case study: one review session (real-world impact)

*Purpose:* the centerpiece. It shows GridLens used as intended, on a public grid, with times. About 110
words, plus V4. Use a screenshot of the Agent tab for one step only, with synthetic data.

Setting: the synthetic Texas7k case, a 6,717-bus public test grid. A reviewer asks five questions in turn.

V4, storyboard: five rows, each with the question, the tool that answered it, one line of the answer with its
citation, and the turn's time and tokens.

| # | Reviewer asks | Tool | What comes back (draft excerpts from measured runs) | Time |
|---|---|---|---|---|
| 1 | "What was this study, and what did it run?" | `get_run_configuration`, `read_file` | Case, settings, input hashes, 8,891 contingencies | **[measure]** |
| 2 | "Which lines exceed their rating under N-1?" | `rank`, `rank_groups` | Top lines with loading, the binding outage, and the count of lines above 100% | **[measure]** |
| 3 | "Which single outages would island load?" | `topology` | 1,061 outages split the network; the largest cuts off 115.0 MW at three MIDFIELD buses | 41 s |
| 4 | "What if Coast load grows 5%?" | `start_sensitivity_run` (preview) | 1,022 loads, +1,006.5 MW; the swing generator is rated 275 MW, so contingencies may fail; nothing runs until confirmed | 61 s |
| 5 | "How does NERC define total transfer capability?" | `search_documents` | TTC = base transfer level + first-contingency incremental transfer capability, NERC ITCS Overview, p. 18 | 21.5 s |

Rows 3–5: live runs with nemotron-3.5-lightning on 2026-09-30, in a scratch copy of the sample project
(`$CLAUDE_JOB_DIR/tmp/live/`, session folders there). Rerun all five in one session for the poster, and take
the times from `conversation.md`, which records each turn's time and tokens.

Takeaway line above V4: "A regulator's five questions, answered on one workstation, each answer traceable to
the calls that produced it."

Why row 4 matters for a regulator: when this evaluation's own preparation added load to Coast without
offsetting generation, the run overloaded the 275 MW swing generator and left only the base case
(`docs/plans/agent_question_evaluation.md`, step 2). The preview now catches that before minutes of compute.

### Panel 7. What no published system combines

*Purpose:* the technical distinction, stated once, with evidence for the priority claim. About 50 words,
plus Table 7.

Draft lead: Published power-system agents serve operators, planners, and engineers. None we found is built
for regulators, and none combines local inference, open code, an industry case format, and enforced review
of changes at this scale.

Table 7 (keep to eight rows; each cell as the paper states it; "not stated" where it does not):

| System | Intended user | Inference | Solver and case | Largest case evaluated | Changes need approval |
|---|---|---|---|---|---|
| **GridLens (this work)** | Regulators and their staff | Local, loopback enforced | GridPACK, PSS/E RAW 33–35 | 6,717 buses, full N-1 (8,891) | Yes, next user message |
| X-GridAgent (Wen & Chen, 2025) | Engineers, operators | Hosted API | pandapower | 2,000 buses | Not described |
| GridMind (Jin et al., 2025) | Domain experts in analysis and operations | Hosted APIs | pandapower | IEEE 300 | Not described |
| Governance-aware digital twin (Mylonas et al., 2026) | TSO control room | Local (Ollama) | pandapower | 35 buses | Yes, approval tokens |
| Grid-Orch (Liu et al., 2026) | Distribution engineers | Hosted or local | OpenDSS | Distribution feeders | Not reported |
| Grid-Mind (Shamseldein, 2026) | Interconnection studies | Hosted API | pandapower, ANDES | IEEE 118 | Not reported |
| eGridGPT (Choi et al., NREL, 2024) | Control-room operators | Local | Digital twin | Pilot | Operator decides |
| PowerAgent (Zhang & Xie, 2025) | Utilities, operators | Any | PSS/E, PowerWorld (via MCP) | No evaluation | Proposed |

Below the table, three one-line technical distinctions, the only ones the poster claims:

- Whole-population answers over an 8.7 GB result: statistics use every facility and say how many.
- Topology checked against the solver: the 82 outages that cut off two or more buses are exactly GridPACK's
  82 ISLANDED contingencies (Panel 9, V5).
- Approval enforced in the tool layer, not asked of the model in the prompt: the one change made without
  confirmation in the first evaluation stopped once the rule moved into the tool (Panel 9).

Source: `docs/plans/literature_comparison_2026-09-30.md` §1–4. **[verify every cell against the paper before
print; add a "code available" column only after checking each repository]**

### Panel 8. Benchmarking methods

*Purpose:* the required section: be explicit. About 70 words, as a compact table.

| Item | Specification |
|---|---|
| Hardware | NVIDIA DGX Spark: GB10 (20 Arm cores: 10 Cortex-X925, 10 Cortex-A725; Blackwell GPU), 128 GB unified memory; DGX OS 7.2.3 (Ubuntu 24.04.5, aarch64); driver 580.178.04; CUDA 13 |
| Grid | Texas7k synthetic case (Texas A&M Electric Grid Test Case Repository), PSS/E v33: 6,717 buses, 5,095 loads, 731 generators, 7,173 branches, 1,967 transformers, 8 areas |
| Study | Full branch and generator N-1: 8,891 contingencies; monitored facilities at or above 50 kV (6,823 lines) |
| Solver | GridPACK `ca.x`, 20 MPI ranks, Docker `--network none`; images `pnnl/gridpack:ca-scalability-v2` and a cuDSS build |
| Analysis | cudf-cu13 26.6.0, dask-cudf-cu13 26.6.0, pandas 2.3.3, pyarrow 23.0.1 |
| Agent | Hermes Agent 0.21.4, Ollama 0.34.2; models nemotron-3.5-lightning, gemma4:31b, nemotron3:33b; 18 MCP tools |
| Agent evaluation | 30 regulator-style questions (32 prompts), each in a fresh session; reference answers computed from the data independently of the agent; scored Pass, Partial, or Fail on numbers, evidence, citations, claims of action, and plain language **[state who scored: currently Claude; add blinded human scoring, 9.3]** |
| Reduction timing | Analysis cache rebuilt from the 8.7 GB result file in a fresh process with a cold page cache; three trials per backend, median reported; peak memory is the rise in system-wide used memory, which includes GPU allocations on unified memory (`scripts/benchmark_csv_flat_backends.py`) |
| Agent timing | Wall clock from audit timestamps: turn time, time in tools, time in model, and tokens (`agent/accounting.py`) |
| Tests | 450 automated tests on synthetic fixtures |

Sources: this machine; `scripts/prepare_agent_evaluation.py`; `docs/plans/agent_question_evaluation.md`;
`python -m pytest` on 2026-09-30.

### Panel 9. Results

*Purpose:* measured outcomes, as three small visuals and a short list. About 80 words.

**Headline results** (four bullets, like the 2026 winner's "Key Achievements"):

- Full N-1 of 8,891 contingencies in 227 s; the event index over 74.7 million result rows builds in about
  101 s and answers a single-contingency query in under 0.1 s.
- Topology predicts GridPACK's islanded set exactly: 82 of 82.
- Evaluation-driven fixes raised passes on the 13 affected prompts from 3 to 7, and cut their time from 144
  to 44 minutes.
- Of 3 h 13 min of agent time in the evaluation, 2 min 30 s was in GridLens tools; the rest was local model
  inference, which is where GPU work pays off next.

V5, topology validation (stacked bar or Sankey), 1,061 single outages that split the network:

- 82 cut off two or more buses: all 82 are GridPACK ISLANDED, and GridPACK reports no other ISLANDED.
- 978 cut off one bus without the swing bus: GridPACK solved them without that bus (897 OK, 81
  SLACK_OVERLOAD).
- 1 cuts off the swing bus itself: GridPACK DIVERGED.

Source: `topology` on run `2026-07-28_14-46-26` against its convergence CSV (recomputed 2026-09-30).

V6, agent evaluation (grouped bars, Pass/Partial/Fail):

- gemma4:31b, all 32 prompts, first run: 11 / 16 / 5.
- The 13 prompts the tool fixes touched: 3 / 6 / 4 before, 7 / 5 / 1 after.
- Synthetic failure-behavior test (stale cache refused, unselected run refused, citations, units): 16 of 16
  criteria for gemma4:31b and nemotron3:33b.
- **[replace with the re-run of 9.3: both target models, three trials each, pass^k]**

Source: `docs/plans/ai_planning_agent_verification.md`; `docs/plans/agent_evaluation_gemma4_31b_fixes.md`.

V7, where the time goes (one horizontal bar, gemma4:31b evaluation, 32 prompts):

- Model inference and runtime: 3 h 10 min (98.7%).
- GridLens tools: 2 min 30 s (1.3%).
- Annotation: 2.6 million prompt tokens read (71% from cache), 80,798 written, a median of 7.3 output tokens
  per second.

Source: `scripts/render_agent_evaluation.py` on `~/GridLensProjects-eval2/evaluation_report.json`, run
2026-09-30.

Optional fourth visual, if space allows: solver time by image, the same case and XML, both 8,639 of 8,891
converged: 227 s (`pnnl/gridpack:ca-scalability-v2`) and 97 s (cuDSS image with its KLU fallback, no GPU
access). Show it only with that label, and only after 9.2 confirms identical loadings.

### Panel 10. Limits, next steps, and references

*Purpose:* credibility, and the required citations. About 60 words, then references in small type.

**Limits** (three bullets):

- Screening of thermal loading in supplied cases only: no transfer capability, market, or compliance findings.
- Case edits cover loads, generators, and non-transformer branches; generation is not rebalanced.
- Evaluated on synthetic grids; answers scored against computed references, not yet by regulators.

**Next** (three bullets): GPU sparse solves for the contingency power flows; a study with regulatory staff;
a public benchmark of regulator questions on synthetic grids.

**References** (about 12; small type; include the repository URL and QR code here only):

1. CAISO, 2025–2026 Transmission Plan, board-approved update, 2026.
2. U.S. DOE, National Transmission Needs Study, draft for public comment, July 2026.
3. NERC, Interregional Transfer Capability Study Overview, 2024.
4. Q. Zhang and L. Xie, "PowerAgent," *IEEE Power and Energy Magazine* 23(5), 2025. doi:10.1109/MPE.2025.3579718.
5. Y. Wen and X. Chen, "X-GridAgent," arXiv:2512.20789, 2025.
6. H. Jin, K. Kim, J. Kwon, "GridMind," *SC Workshops '25*, ACM, 2025. doi:10.1145/3731599.3767409.
7. C. Mylonas, M. Foti, E. Varvarigos, "A Governance-Aware LLM Orchestrated Agentic Digital Twin for TSO
   Control Room Decision Support," arXiv:2609.22476, 2026.
8. B. Liu, J. Dong, J. Lian, "Grid-Orch," *IEEE OAJPE* 13, 2026. arXiv:2605.12728.
9. B. Palmer et al., GridPACK, PNNL. **[add the canonical GridPACK paper citation]**
10. A. B. Birchfield et al., synthetic grid test cases, Texas A&M. **[add the Texas7k citation]**
11. RAPIDS cuDF; Ollama; Hermes Agent; Model Context Protocol specification. **[add URLs and versions]**
12. R. Prabha, L. Min, R. Rajagopal, Western Interconnection thermal utilization. **[only if public]**
13. GridLens source code, GPL-3.0: https://github.com/alexluhuang/GridLens **[confirm the repository is public
    by the deadline]**

## 6. Visual inventory

| ID | Visual | Panel | Status |
|---|---|---|---|
| V1 | Review gap: utility lane, regulator lane, GridLens bridge | 1 | To draw |
| V2 | Architecture, inputs to cited answer, with the offline boundary | 4 | To draw from `docs/ARCHITECTURE.md` §2 |
| V3 | DGX Spark resource map: cores, GPU, unified memory, with measured sizes | 5 | To draw; data ready (9.1) |
| V4 | Five-question review storyboard, with one Agent tab screenshot (synthetic data) | 6 | Needs 9.4 |
| Table 7 | Comparison with published systems | 7 | Draft above; verify cells |
| V5 | Topology validation, 1,061 outages by GridPACK status | 9 | Data ready |
| V6 | Evaluation Pass/Partial/Fail | 9 | Data ready; replace after 9.3 |
| V7 | Time split, model vs tools | 9 | Data ready |

## 7. Draft word count

| Panel | Words |
|---|---|
| 1 Review gap | 90 |
| 2 Goal and scope | 80 |
| 3 Trust controls | 80 |
| 4 System | 60 |
| 5 NVIDIA technology | 110 |
| 6 Case study | 110 |
| 7 Distinctiveness | 50 |
| 8 Methods | 90 |
| 9 Results | 80 |
| 10 Limits and next | 60 |
| **Total** | **about 810**: cut to about 600 in layout, starting with Panels 3 and 6 |

## 8. What to leave off

- Implementation detail a visitor cannot use at a glance: file names, cache versions, adapter pinning, the
  job record format.
- Any comparison with commercial tools (PSS/E, PowerWorld) by price or feature list.
- The literature review's full critique of each paper; Table 7 is enough.
- Screenshots of real projects, real bus names from non-synthetic cases, or anything from a CEII case.
- Claims about productivity for regulators until a study measures it (9.5).

## 9. Measurements to take before printing

Each item names what to run, how, and what the poster needs from it.

1. **GPU vs CPU result reduction** (Panel 5, V3). **Done 2026-10-01.** `scripts/benchmark_csv_flat_backends.py`
   on the 8.7 GB flat result of run `2026-07-28_14-46-26`, copied to `~/GridLensProjects-bench`. Each trial
   ran in a fresh process with the run's inputs evicted from the page cache (`posix_fadvise`; `mincore`
   showed the file going from 100% to 0% resident), rebuilt the cache with `rebuild=True`, and alternated
   backends within each of three rounds. Results: `~/GridLensProjects-bench/results_2026-10-01/summary.json`.

   | Backend | Reduction, median (range) | Whole cache build, median | Peak memory rise | GPU use, peak / mean |
   |---|---|---|---|---|
   | cuDF | 13.0 s (12.7–13.5) | 13.5 s | 22.7 GB | 96% / 32% |
   | dask-cuDF | 141.2 s (141.0–142.5) | 141.8 s | 8.9 GB | 39% / 6% |
   | Dask, 20 CPU threads | 131.6 s (130.6–132.2) | 132.1 s | 30.4 GB | 0% (see below) |
   | Python streaming | 1,231.9 s (1,229.4–1,234.9) | 1,232.4 s | 0.1 GB (RSS) | 0% (see below) |

   - **Agreement.** In every trial, all four backends give identical maximum loading, overload count, and
     contingency count for all 8,646 facilities. The binding contingency differs only where the maximum is
     tied. 1,070 facilities reach their maximum in more than one contingency, 407 of them at 0% loading.
     cuDF and dask-cuDF choose among the tied contingencies differently on each run. All 1,177 mismatches
     at nonzero loading were checked against the raw rows, and every one is an exact tie. Python and CPU
     Dask always agree. Make the GPU tie-break deterministic before claiming identical results without
     qualification.
   - **CPU Dask** runs in GridLens only when cuDF and dask-cuDF are missing, so for that trial the script
     makes them look unavailable. `GRIDLENS_ALLOW_CPU_DASK=1` alone silently falls back to Python
     streaming on this machine. Otherwise the timed code is the production path.
   - **dask-cuDF is slower than CPU Dask here**: one Dask-CUDA worker, with mean GPU use of 6–8%. GridLens
     chooses it automatically only for result files larger than 75% of available memory, so it does not run
     on this file in normal use. Leave it off the poster, or measure it on a file that needs it.
   - **Memory** is system-wide used memory (MemTotal − MemAvailable) above the pre-run baseline, so on
     unified memory it includes GPU allocations; it is not a GPU-only figure. Python's rise was within the
     noise from other processes, so its RSS is given.
   - The 13 s includes importing cuDF and creating the CUDA context. The desktop session briefly used the
     GPU during some CPU trials (peaks of 24–30%, means of 2% or less). CPU times varied by under 1.5%
     between trials.
2. **GridPACK with GPU sparse solves** (Panel 5 "Next", optional V8). Run the same case with the cuDSS image
   given GPU access (add `--gpus all` in extra Docker arguments; the network stays off), with its KLU
   fallback, and with `pnnl/gridpack:ca-scalability-v2`; three runs each. Check that convergence counts and
   maximum loadings match. Explain the 8.7 GB vs 9.2 GB output difference before comparing.
3. **Agent evaluation re-run** (V6, Panel 8). Run the 30 questions with nemotron-3.5-lightning and gemma4:31b,
   three trials each, with the harness's accounting. Report pass^3 (all three pass) beside the mean, and
   time and tokens per model. Have one person score blinded, and report agreement with the automatic scores.
4. **The five-question session** (Panel 6, V4). Ask the five questions in one session with
   nemotron-3.5-lightning on a scratch copy of the sample project. Take the answers, citations, times, and
   tokens from `conversation.md`, and the screenshot from the Agent tab.
5. **A small regulator study** (optional; unlocks an impact claim). Three to five regulatory staff do the
   five tasks with GridLens and with the filing alone. Measure time, correct answers, and questions they
   would send the utility. Without it, the poster claims capability and measured time, not productivity.
6. **Checks before print:** verify Table 7 cells against the papers; confirm licenses for every component;
   confirm the Prabha et al. paper's status; confirm the repository is public; confirm the GTC 2027 size and
   template.
