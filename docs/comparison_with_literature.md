# Comparison with literature: GridMind

This document compares the GridLens Agent tab with the architecture in one published system:

> Hongwei Jin, Kibaek Kim, and Jonghwan Kwon. 2025. GridMind: LLMs-Powered Agents for Power System Analysis
> and Operations. In Workshops of the International Conference for High Performance Computing, Networking,
> Storage and Analysis (SC Workshops '25). ACM. https://doi.org/10.1145/3731599.3767409

The comparison was made on 2026-09-22 against the working tree at that date, including uncommitted changes to
the agent package. File and function references are to `src/gridlens/agent/` unless stated otherwise.

Later the same day the Agent tab changed in ways this comparison predates. Like GridMind's agents, it now
drives the solver: it creates projects, writes the GridPACK XML, starts runs, and builds analyses, through
background jobs rather than an in-process solver. Tool results have no row cap, and new file tools read
every field of every project file. Sections below that describe GridLens as read-only, as limited to the
selected runs, or as having fifteen tools describe the earlier state.

## GridMind in brief

GridMind is an Argonne National Laboratory prototype that answers power system questions in natural language.
A language model interprets the request, plans the steps, and explains the results. Every number comes from
PandaPower, which GridMind calls as a tool. The system has two domain agents: an ACOPF agent (tools
`solve_acopf_case`, `modify_bus_load`, `get_network_status`) and a contingency analysis agent (tools
`solve_base_case`, `run_n1_contingency_analysis`, `analyze_specific_contingency`, `get_contingency_status`).
The paper also names a planner and a coordinator, but gives no prompt, logic, or evaluation for either.

The agents share a structured session state built from Pydantic models such as `ACOPFSolution` and
`ContingencyAnalysisResult`. That state holds the active network, a log of the user's edits (load changes,
outages), cached solutions, and provenance. Contingency results are cached under a key made from the case,
the outage, and a hash of the edits, so the contingency agent can tell whether an ACOPF solution is still
current after a change. The implementation uses PydanticAI.

The evaluation covers six hosted models on IEEE test cases. Every model solved ACOPF for case118 correctly
over five runs. On contingency ranking, five of the six models reported the same top five lines, and GPT-5
Mini reported a different set.

Two gaps in the paper matter for this comparison. The system prompt published in the appendix does not
contain the "never fabricate solver outputs" rule that the main text quotes. The automatic recovery, diff
replay, and caching that the paper describes are not measured.

## Summary

GridLens takes GridMind's central idea, that the model explains and deterministic code computes, and
enforces it more strictly. It differs in three ways. It is a single agent. It reads completed runs and does
not run solvers or support what-if edits. Its tool outputs are dictionaries inside a common envelope, not
typed schemas. The first two differences suit the feature's current scope. The third, and the lack of any
voltage tool, are the gaps worth closing.

## Where GridLens matches or exceeds GridMind

### The model does not supply numbers

`SYSTEM_PROMPT` in `prompt.py` tells the model to use only GridLens tools to establish facts and never to
invent numerical results. The fifteen tools in `tools.py` are the model's only access to run data. GridMind
states the same rule in its text, but its published prompt leaves it out.

### Auditability is enforced

GridMind says every reported number maps to a field in a stored tool output, but shows no mechanism for it.
In GridLens, `ToolService._invoke` gives every call an ID (`T1`, `T2`, ...) and writes a started and a
completed record to an append-only audit. After each turn, the controller processes the answer:

- `normalize_citations` rewrites any cited ID that is absent from the audit as `invalid source`;
- `cite_uncited_turn` appends the turn's sources when the model cited none;
- `disclose_truncated_results` appends a note when a result was cut by row limits and the model did not
  say so.

### Validation covers the data

GridMind validates solver convergence and power balance. GridLens refuses caches whose dataset or parser
version is wrong, or whose file times show they are older than their source (`ToolService._tables` and
`_optional_table`). It counts failed and unconverged cases and reports them. It also warns about rating-basis
mismatches, facilities excluded by filters, and base-case rows included in maximum loading. The system prompt
requires the model to repeat the relevant caveats.

### Contingency ranking is deterministic

GridMind's contingency agent ranks critical elements by LLM reasoning over solver output, which is why one
model disagreed in the paper's Table 1. `rank(object="contingencies")` sorts by a named metric in code, so
every model should receive the same ranking.

### The evaluation scores failure behavior

GridMind scores ACOPF success and latency. `test_installed_local_models_share_tools_and_prompt` in
`tests/test_agent_hermes_installed.py` runs six local models with the same prompt and tools. It scores tool
choice, arguments, numeric fidelity, units, metric wording, convergence caveats, citations, and truncation
disclosure. It also scores two behaviors the paper does not test: refusing to read an unselected run, and
refusing to invent a value when the cache is stale.

### Security and governance

The paper does not discuss data governance. GridLens has loopback-only routing and a hosted-provider gate
(`policy.py`), per-session path scoping (`SessionContext` and `scoped_path` in `session.py`), treatment of
run files and tool output as untrusted input, and a sandbox for generated scripts that runs only after human
approval (`scripts.py`). See `docs/security_ceii.md`.

## Where GridLens differs

### One agent instead of a planner and specialists

GridLens has one agent, one prompt, and fifteen tools. The paper gives no evidence that its planner and
coordinator improve results, and the GridLens evaluation shows six models choosing tools correctly from a
single list. A split should be reconsidered only if the tool list grows substantially, for example when run
launching is added, or if the evaluation shows models confusing the loading tools with the contingency
tools.

### Read-only analysis instead of solving and re-solving

GridMind's context management (edit log, freshness checks, cache keys that include an edit hash) exists to
support what-if edits. GridLens works on completed runs that do not change, so it needs none of that. Its
counterparts are the immutable `SessionContext` and the cache freshness checks. Launching runs is deferred in
`docs/plans/ai_planning_agent.md`. When that work starts, Section 3.4 of the paper is the part worth
borrowing: an edit log for each run, and a check of whether a cached result is still current for those edits.

### Transcript instead of structured memory

GridMind keeps a memory object with the current case, the latest solution, and the edits, and feeds it back
into the model's reasoning. GridLens keeps a transcript. For a runtime that cannot resume a session,
`turn_prompt` replays a shortened transcript marked as untrusted, and tells the model to rerun any tool whose
result it wants to cite. With read-only data, requerying is cheap, and it gives the model fresh results to
cite in place of numbers it remembered. This suits GridLens better than GridMind's approach would.

### External agent runtimes instead of an in-process framework

GridMind runs its agent loop inside PydanticAI. GridLens drives Hermes, Claude Code, or Codex through the
`RuntimeAdapter` protocol (`runtime.py`) and exposes its tools over MCP (`mcp_server.py`). GridLens gains
provider independence and does not maintain an agent loop of its own. The cost is that it cannot insert a
validation step inside the model's loop. `AgentController.run_turn` compensates by checking the answer after
the turn.

### Remedies instead of automatic recovery

GridMind describes automatic recovery after a failed validation, such as adjusting tolerances or switching
algorithms, but does not evaluate it. GridLens returns a stable error code and a remedy written for the user;
`ANALYSIS_NOT_BUILT`, for example, tells the user to rebuild in the Agent tab. This fits a tool that must not
change run artifacts on its own.

### Generated scripts

GridMind avoids ad hoc scripts entirely. GridLens allows them only as proposals (`propose_analysis_script`)
that a person reviews and that run in a network-isolated sandbox, with output labeled untrusted. That covers
questions the fixed tools cannot answer, a case the paper does not address.

## Gaps worth closing

1. Voltage. GridMind's contingency agent considers voltage excursions as well as thermal overloads. Since
   2026-09-24, `rank(object="cases", metric="min_voltage_pu")` ranks the end voltages recorded for each
   contingency in the drill-down index, and qualifiers select the outage and the area. The flat result records
   voltage only at the ends of monitored branches, so this is not a bus-by-bus voltage scan. A voltage
   column in `contingency_summary` would let contingencies be ranked by their lowest voltage without the index.

2. Typed output schemas. Section 3.3 of the paper argues that typed fields such as `min_voltage_pu` give the
   model exact names to refer to. GridLens tool inputs are typed, but every tool returns `dict`, so the MCP
   server advertises no output structure and the model learns field names only after a call. A TypedDict or
   Pydantic model for each tool's rows would let the SDK publish output schemas and let tests catch changes
   in row shape. The envelope would not change.

3. Checking numbers against citations. `normalize_citations` confirms that a cited ID exists, but not that a
   value such as "120%" in the answer appears in that call's result. A check that flags numbers in the answer
   that appear in no result cited in the same turn would go beyond what GridMind claims, and would support
   the plan's statement that the agent is not a source of numerical truth. Neither system does this today.

4. Evaluation breadth. The installed-model test asks four questions against one fixture and scores answers
   with regular expressions. GridMind ran each case five times, and a single run can hide variation between
   runs of the same model. Two additions would be cheap: repeat each question several times per model, and
   add a contingency-ranking question that checks every model reports the same top event IDs. GridMind's
   Table 1 failed that check; GridLens should pass it by design. The 30-question evaluation of 2026-09-24
   covers run comparison and case drill-down; see `plans/ai_planning_agent_verification.md`.

## Not recommended

- A planner and coordinator split, for the reasons under "One agent instead of a planner and specialists."
- Ranking critical elements by LLM judgment. If a combined thermal and voltage criticality score is wanted,
  define it in code and document it as a metric, as thermal margin is.
- Automatic recovery that rebuilds caches or reruns analysis without the user asking.
