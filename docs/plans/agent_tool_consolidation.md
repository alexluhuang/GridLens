# Agent tool consolidation (2026-09-24)

The agent's catalog went from 35 tools to 15. The aim was to have the model fill in the parameters of a
few general tools and chain calls, rather than choose among many tools that each answer one kind of
question. No capability was dropped: every removed tool's job is a call, or a short chain of calls, to the
tools that remain, and several questions the old catalog could not answer now have deterministic answers.

This document describes every change. The commits are on branch `agent-tool-consolidation`:

| Commit | Change | Lines |
|---|---|---|
| `eb91790` | Fold the loading tools into `rank` and `rank_groups` | 371 |
| `916675c` | Read every file with one `read_file` tool | 772 |
| `af284ee` | Report status and stop work through two tools | 198 |
| `bf1feb4` | Query the drill-down index by any qualifier | 318 |
| `5578db8` | Move the rank vocabulary into `agent.objects` | 516 |
| `fbf4858` | Rank contingencies and cases, and compare runs, with `rank` and `rank_groups` | 714 |
| `12b976d` | Assign generator outages to their bus's area and drop removed tool names | 49 |
| `c0e500d` | Count every qualifying object, whether or not its metric is known | 45 |
| `048d1d7` | Count overloads by loading alone, leaving out GridPACK's violation flag | 163 |
| `50fc80b` | List qualifying objects with no known value after the ranked ones | 81 |
| `c09c80a` | Select tie lines directly, and refuse qualifiers no object can meet | 112 |
| `1021b89` | Join tables in read_file | 159 |
| `125acfe` | Tell scripts where the run's files are, and let the sandbox load pyarrow | 97 |
| `ff8305c` | Make destructive changes wait for the user's confirmation in a later turn | 245 |
| `a4f0c81` | Update the evaluation scripts for thermal counts and repeated runs | 27 |
| `a5e3a00` | Flag totals of branch flows measured in different directions | 36 |

`12b976d` and `c0e500d` fix defects found while preparing the local-model evaluation. The six after them fix
the gaps that the evaluation of gemma4:31b exposed, and `a5e3a00` fixes one that the re-run exposed; §12
describes them. `ai_planning_agent_verification.md`
reports both evaluations.

## 1. Rules the consolidation followed

- Parameterize by object and metric, not by question. One tool sorts objects, one groups them, and one
  reads files.
- Keep read-only, write, and destructive actions in separate tools. The MCP annotations (`readOnlyHint`,
  `destructiveHint`) and the confirmation the destructive tools require depend on that split.
- Keep domain rules inside the tools: facility types, the 50 kV cutoff, unknown loading without a rating,
  endpoint control areas, and convergence. The model chooses; the tool applies the rules.
- A tool earns its place if it holds logic the model cannot reproduce by chaining calls, or a side effect no
  other tool has.

## 2. The catalog

| Tool | Kind | Replaces |
|---|---|---|
| `rank` | read | `rank_branch_loading`, `list_thermal_violations`, `get_branch_loading`, `compare_runs`, `rank_contingencies`, `get_contingency_flows`, `get_branch_contingencies` |
| `rank_groups` | read | `summarize_loading`, `summarize_convergence` |
| `read_file` | read | `describe_file`, `query_table`, `read_text_file`, `read_document`, `get_run_method`, `search_buses`, `get_script_result` |
| `list_files` | read | `locate_run_artifacts` |
| `list_projects` | read | |
| `get_project` | read | `get_run_inventory` |
| `get_status` | read | `get_run_status`, `get_job`, `list_jobs` |
| `get_run_configuration` | read | |
| `create_project` | write | |
| `add_project_inputs` | destructive | |
| `configure_run` | destructive | |
| `start_run` | write | |
| `run_analysis` | write | |
| `stop` | destructive | `stop_run`, `cancel_job` |
| `propose_analysis_script` | write | |

Every call sends the tool definitions to the model. Measured as each tool's name, description, and input
schema as the MCP server lists them, the 35 tools of the branch's base (`e2957db`) took 23,171 characters and
the 15 take 18,332, 21% fewer. The system prompt grew from 3,838 to 4,961 characters to describe the object
families and the chains between them, so a call carries 23,293 characters of prompt and tools instead of
27,009, 14% fewer. `rank` and `rank_groups` are half of what remains (5,059 and 4,282 characters), because
their enums name every metric, field, and group of three families. The saving is smaller than the tool count
suggests: before `rank` and `rank_group` were added (`f275a97`), 33 tools took 17,679 characters.

The fixes in §12 gave the model more to read: how to select tie lines, the sandbox's layout, joins, and the
confirmation flow. The 15 tools now take 22,116 characters, 5% fewer than the 35, and the system prompt
6,273, so a call carries 28,389 characters of prompt and tools, 5% more than before the consolidation. The
evaluation showed that the model needs that text, so this document does not propose trimming it.

## 3. rank and rank_groups

```
rank(run_id, object, order, metric, magnitude, filters, fields, compare_run_id, compare_project, project)
rank_groups(run_id, group, object, order, metric, statistic, magnitude, filters, compare_run_id, compare_project, project)
```

`rank` returns the first `magnitude` objects (0 for all) in `order` by `metric`, each with the value it was
sorted by and the extra `fields` asked for. `rank_groups` returns the first `magnitude` groups by
`statistic` of `metric` over each group's objects, each with that statistic and the count of objects it
used. Facility and contingency results also state the units, the definitions, how many objects were in
scope, how many the qualifiers removed, and how many had no known value; case results state how many index
rows were recorded and how many qualified.

### Object families

The vocabulary is in `gridlens/agent/objects.py`. Each family has its own metrics, fields, and groups; a
choice outside the family is refused with the list of valid ones.

| Family | object | Population | Metrics | Groups |
|---|---|---|---|---|
| Facilities | `branches`, `transformers`, `both` | The analysis cache's facilities of that kind at or above 50 kV, as the GUI charts count them | `max_utilization_pct`, `base_utilization_pct`, `mean_utilization_pct`, `min_utilization_pct`, `thermal_margin_pct_points`, `overload_count`, `contingency_count`, `rating_mva`, `nominal_kv` | `control_area`, `tie`, `voltage_class`, `nominal_kv`, `branch_type`, `binding_contingency` |
| Contingencies | `contingencies` | Outage cases from the compact `contingency_summary`, joined to the convergence file; the base case is not a contingency | `max_loading_pct`, `overload_count`, `monitored_facility_count`, `iterations`, `max_p_mismatch`, `max_q_mismatch` | `type`, `status_code`, `converged`, `outage_area` |
| Cases | `cases` | Every row of the drill-down index: one facility in one contingency, base case included | `loading_percent` (absolute), `mva_from`, `p_from_mw`, `q_from_mvar`, `rate_mva`, `v_from_pu`, `v_to_pu`, `min_voltage_pu`, `ang_from_deg`, `ang_to_deg`, `angle_difference_deg` | `contingency`, `facility`, and every facility and contingency group |

`overload_count` counts cases at or above 100% loading for a facility, and monitored facilities at or above
100% for a contingency. GridPACK's `viol` flag is not counted: it marks the outaged branch itself in 3,361 of
the 3,541 cases it flags in the sample run, and misses 17,287 cases at or above 100%. It stays available as
the case field `viol`.

A case carries the fields of its facility (control area, tie, voltage class, nominal kV, branch type, buses,
bus names, circuit, section) and of its contingency (event_idx, name, type, convergence, status, outage
area). A qualifier such as `control_area` or `outage_area` therefore means the same thing on facilities,
contingencies, and cases, and a drill-down is a second call with the first result's keys as qualifiers:
from a facility to its cases, or from a contingency to its cases.

The statistics are `mean`, `median`, `min`, `max`, `std` and `var` (population, dividing by n), `iqr`
(interpolated as the GUI box plots are), `count`, and `sum`, which is for additive quantities such as MW.
`count` takes every qualifying object whether or not its metric is known, so counting contingencies by status
includes the failed ones, which have no loading.
"Mean max utilization" is `statistic="mean"` of `metric="max_utilization_pct"`; "mean mean" and "mean min"
use `mean_utilization_pct` and `min_utilization_pct`.

### Qualifiers

`filters` is a list of `{"column", "op", "value"}`. An object is kept only when every qualifier holds.

- `op` is `==`, `!=`, `<`, `<=`, `>`, `>=`, `contains`, `startswith`, `in` (a list), or `matches`, the PSS/E
  name match that also accepts an exact ID.
- A two-ended field (`control_area`, `outage_area`, `bus`, `bus_name`) matches when either end does; `!=` must
  hold at both ends. One `control_area` qualifier per area therefore selects the ties between two areas, and
  `tie == "true"` with one `control_area` selects all of an area's ties. `control_area` lists the from end's
  area first.
- A value no object has is refused with `UNKNOWN_VALUE` and the values that exist, for `control_area`,
  `outage_area`, `voltage_class`, and `branch_type`. For fields where a value can simply not occur, such as
  a status no contingency ended with, a warning says so instead.
- A name given to a bus-number or event-number field, which can never match it, is refused with a pointer
  to `bus_name` or `contingency`.
- An unknown value, such as the loading of a facility without a positive rating, meets no qualifier.
- Case metrics and `viol` take only numeric operators.

### Defaults that keep answers honest

- Facilities without a positive rating have unknown loading, never ranked or averaged at the 0% GridPACK
  reports. `rank` lists such objects after the ranked ones, with rank and value null, and counts them in
  `without_value`; statistics leave them out and report `excluded_unknown_value`. A contingency whose
  solution failed records no flows, so its loading is unknown in the same way, and a qualifier on its status
  still lists it. The Branch Analysis chart averages unrated facilities in, so its means can differ when a
  run has any; the sample run has none.
- Contingency rankings include converged cases only, unless a qualifier or the group names `converged` or
  `status_code`, and a warning says how many were left out.
- Cases include the base case and non-converged contingencies, as the index records them. A warning names
  any returned case in a failed contingency, and every case result states that voltages and angles are
  recorded only at the ends of monitored branches.
- When `max_utilization_pct`, the facility default, is given for contingencies or cases, the family's own
  maximum-loading metric is used instead, with a warning.

### Outage areas

GridPACK names an outage after its element: `BR_<from>_<to>_<circuit>` for a branch and `GN_<bus>_<id>` for
a generator. `outage_area` is the control areas of those buses, named as facility ends are: from the
facilities' endpoints, and otherwise from the cached bus table, since a generator's terminal bus is often at
the end of no monitored facility. A name in another form gets `unknown`. In the sample run every one of the
8,891 contingencies, including the 731 generator outages, has a known outage area.

### Comparing runs

`compare_run_id` (with `compare_project` for a run in another project) aligns facilities with the other run
by full branch key and uses the change in the metric, other run minus this run, as each object's value:
percentage points for loadings. Qualifiers may then use `compare_value` (the other run's value), `change`,
and `rating_changed`, so new overloads are `max_utilization_pct < 100` with `compare_value >= 100`, and
resolved ones the reverse. Results count the facilities found in only one run (`only_in_run`,
`only_in_compare_run`) and those whose rating changed. `rank_groups` with a compare run averages, or
otherwise summarizes, the changes per group. Only facilities can be compared.

## 4. read_file and list_files

```
read_file(path, project, table, columns, filters, sort_by, descending, group_by, statistic, value_column, compare_path, as_text, join, offset, limit)
```

`read_file` reads any project file, or any file in this session's folder, as rows:

- a table (CSV, GridPACK text table, or Parquet), or the RAW section named in `table`;
- a RAW case without `table`: its sections, record counts, and columns, which is what `describe_file` showed;
- a JSON or XML document: one row per field, as `path` and `value`, with XML sections in the path, so
  `Contingency_analysis/qlim` and `Powerflow/qlim` stay distinct;
- other text, or any file with `as_text=True`: numbered lines. Filtering lines with `contains` searches a
  log.

The same filters, sorting, column selection, and paging apply to every kind. Every result states the kind,
the columns, and the total row count. With no filter or sort, a CSV, text, or Parquet file's count comes
from a line count or the Parquet footer rather than a parse, so reading the first rows of a multi-gigabyte
file is quick.

`group_by` summarizes every matching row per value of a column, with `statistic` of `value_column`, for
example the total load by area: `table="load"`, `filters=[STATUS == 1]`, `group_by="AREA"`, `statistic="sum"`,
`value_column="PL"`. Running totals keep memory flat, and only median and iqr hold values.

`join` adds columns from another table to each row, from the first row whose `right_on` value, by default
`left_on`, equals the row's `left_on` value. The other table is a RAW section of the same file or another
project file, joins apply in order before filters and grouping, and a second join can use a column the first
added. A PSS/E generator record has no area of its own, so generation by area is `table="generator"`,
`join=[{"table": "bus", "left_on": "I", "columns": ["AREA"]}]`, `group_by="AREA"`, `statistic="sum"`,
`value_column="PG"`. A joined column the rows already have is named after its table, as `BUS.AREA`, and rows
with no match get blank columns and a count in the warnings.

`compare_path` returns only the fields where two JSON or XML documents differ, marked `changed`, `only in
file`, or `only in compare file`, with the number of fields compared. Two runs' `manifest.json` or
`input.xml` files compared this way list every difference in settings, command, image, and input hashes.

`matches` adds `match_kind` (`exact`, `prefix`, or `fuzzy`) to each row and returns exact matches first.
Fuzzy matching now runs past a stored name only when that name looks cut: it has a `~` marker or is at least
twelve characters long. Before, a query such as "east bernard" also matched a separate bus named "EAST".

A file in a session's `generated/` folder, where script proposals and their output are, is marked untrusted
in the result's warnings. `list_files` now also lists an absolute folder inside a project or this session,
which is how the agent finds a script's `result.json`, and its description names the run folder layout.

## 5. get_project, get_status, and stop

- `get_project`'s rows are now the project's runs, newest first, with status, whether each has an analysis
  cache and whether that cache is current (`analysis_current`), its cached tables, and whether it has a
  drill-down index. The input files moved to `input_files`. When `project.json` lacks the fields the Project
  tab saves, it warns and still lists the runs.
- `get_status(job_id=...)` reports a job and can wait up to 1,500 seconds for it; `get_status(run_id=...)`
  reports a run's status, contingency progress, log tail, and latest job, and can wait for that job;
  `get_status()` lists the project's jobs. Giving both IDs is refused with `ONE_TARGET`.
- `stop(job_id=...)` cancels a job; `stop(run_id=...)` stops the run's job, or its Docker container when no
  job started it. Exactly one ID is required.
- Over MCP, `configure_run` on a project that has an XML, `add_project_inputs` replacing an input or
  switching the XML, and `stop` on something running first return a preview and change nothing. The change
  is made when the same call returns with `confirm=True` after the user has sent another message; §12
  explains why.

## 6. The drill-down index

`analysis/event_index.py` now stores the flow, voltage, and angle columns as numbers, reading a blank or
unparseable cell as missing. `INDEX_VERSION` moved from 2026.09.22 to 2026.09.24, so an index built before
this change reports `INDEX_STALE` and must be rebuilt with `run_analysis(include_index=True, rebuild=True)`.

`query_event_index`, which served two fixed lookups, is replaced by two queries:

- `scan_cases` ranks the rows that pass the qualifiers by one metric and holds only the best rows. It prunes
  buckets when events are named, reads only the columns it needs, and keeps ties in event and full-key
  order.
- `group_cases` computes a statistic per group, by event or by facility, merging per-batch running totals.
  A facility or event may belong to more than one group.

`IndexStale`, `IndexColumnsMissing`, and `TooManyCases` name the failures, and the tools report them as
`INDEX_STALE`, `CASE_FIELD_UNAVAILABLE`, and `QUERY_TOO_LARGE`. `loading.facility_attributes` describes every
monitored facility, whatever its voltage or type, so cases can be qualified and grouped by their
facility's attributes.

## 7. What each removed tool became

| Removed | Call that does its job |
|---|---|
| `rank_branch_loading` | `rank(metric=..., object=..., fields=[...])` |
| `summarize_loading` | `rank_groups(group="voltage_class" or "control_area", statistic="mean")` |
| `list_thermal_violations` | `rank(filters=[max_utilization_pct >= threshold])`; `total_matching` is the count |
| `get_branch_loading` | `rank(object="both", filters=[from_bus, to_bus, line_id, section], fields=[...])` |
| `compare_runs` | `rank(compare_run_id=...)` |
| `rank_contingencies` | `rank(object="contingencies", metric="max_loading_pct" or "overload_count")` |
| `get_contingency_flows` | `rank(object="cases", filters=[event_idx == N], fields=["p_from_mw", "q_from_mvar"])` |
| `get_branch_contingencies` | `rank(object="cases", filters=[the full branch key])` |
| `summarize_convergence` | `rank_groups(object="contingencies", group="status_code", statistic="count")`, or `read_file` of the convergence file |
| `search_buses` | `read_file` of the RAW case with `table="BUS"` and `NAME matches "..."`, or of a run's bus table with `bus_name matches "..."` |
| `get_run_method` | `read_file` of the run's `manifest.json`, then of its `work/input.xml` |
| `locate_run_artifacts` | `list_files(folder="runs/<run_id>")` |
| `get_script_result` | `list_files` of the proposal's `execution_folder`, then `read_file` of `result.json` |
| `describe_file` | `read_file(path, limit=5)` |
| `query_table`, `read_text_file`, `read_document` | `read_file` |
| `get_run_inventory` | `get_project` |
| `get_run_status`, `get_job`, `list_jobs` | `get_status(run_id=...)`, `get_status(job_id=...)`, `get_status()` |
| `stop_run`, `cancel_job` | `stop(run_id=...)`, `stop(job_id=...)` |

## 8. Answers the old catalog could not give

- Per-contingency MW, Mvar, MVA, end voltages, and angle differences, ranked or grouped over every case in
  the index, with facility and outage qualifiers.
- Totals and counts over any table, and over tables joined by a key, such as in-service load and
  generation by area from the RAW case, or failures by status code from the convergence file.
- Every difference between two runs' settings and inputs.
- New and resolved overloads between runs, and group statistics of the changes.
- Contingencies by type, status, or outage area, and whether an outage in one area overloads another area's
  facilities.

## 9. Other changes

- **Controller.** The checks that verify group-mean and top-line area answers now call and read `rank_groups`
  and `rank(fields=["control_area", "bus_name"])`. Truncation notes for the rank tools say to raise
  `magnitude` instead of paging by offset, and row-scope answers report the requested magnitude. The
  thermal-margin note now also fires for headroom, extra MW, "carry", and transfer questions such as TTC,
  FCITC, and ATC.
- **System prompt.** It is rewritten around the three families and chained calls. It adds the behaviors the
  evaluation checks: wait for the user's confirmation of a previewed change, even when asked; say that GridLens
  cannot edit a RAW case or run a transfer study; state the converged-only default; use `object="both"` before
  a system-wide claim; separate persistent overloads from single worst cases; state voltage coverage and
  draw no stability conclusion from angles.
- **Remedies.** Error remedies in sessions and jobs name `get_project` and `get_status`.

## 10. Tests

The suite passes: 292 tests and 5 opt-in skips, 278 of them before the fixes in §12. The opt-in Hermes
isolation test, which drives the installed
Hermes CLI against a synthetic model server, confirms that exactly the 15 tools are exposed. The opt-in
sandbox test runs a script in the pinned image and reads its result through `read_file`. The tests that
used the removed tools now test the same behavior through the new ones. The new tests cover:

- `rank` and `rank_groups` over contingencies and cases, including qualifiers from both facility and
  contingency fields;
- comparison mode, including new and resolved overloads;
- `read_file` grouping, document comparison, and name matching;
- the index's numeric columns, derived metrics, qualifiers, and grouping;
- `get_status` and `stop`;
- the outage area of a generator outage whose bus only the bus table knows, and counts that include objects
  without a known metric value;
- the fixes in §12: thermal counts from both reducer backends and refusal of an older cache, objects listed
  without a value, tie selection and the value checks, joins, the proposal's sandbox listing and path check,
  the preview-then-confirm flow of each destructive tool, and the notes the controller adds.

## 11. Limits and next steps

- The schema cannot say which metrics, fields, and groups go with which object, so a model can choose a
  combination the tool refuses. The refusal lists the valid choices, and the descriptions group them by
  family.
- An unqualified case scan reads all 64 index buckets of a large run. Naming events prunes buckets; naming
  facilities alone does not.
- Voltages are only those recorded at monitored branch ends, and outage areas need GridPACK's standard
  outage names.
- A run's analysis cache built before 2026-09-24 has no thermal overload counts, so `overload_count` is
  refused with `CACHE_FIELD_UNAVAILABLE` until `run_analysis(rebuild=True)` rebuilds it. Every other metric
  still reads the old cache.
- A sandbox image built from `packaging/agent/Dockerfile` before 2026-09-24 cannot import pyarrow as a
  normal user. Rebuild it, and paste the new image ID into the review dialog.
- A confirmation proves only that the user sent a message after the preview, not that the message agreed.
  The prompt asks the model to confirm only on agreement, and the controller tells the user when a change is
  waiting.
- Sessions recorded before this change cite the removed tools in their audits. They can still be read, but a
  reopened session's new turns use the new catalog.
- The next candidates for new metrics are MW, Mvar, and MVA summaries per facility in the analysis cache,
  so flow questions need no index.

## 12. Fixes after the evaluation (2026-09-24)

The evaluation of gemma4:31b in `agent_evaluation_gemma4_31b.md` exposed six gaps in the tools and a
seventh in how they report an empty result. Each fix is one commit.

| Gap | Symptom in the evaluation | Fix | Commit |
|---|---|---|---|
| Overload counts included GridPACK's `viol` flag | Question 20 classified 241 overloads as new instead of 26, because a line's own outage counted as an overload | Caches record `thermal_overload_count`; `overload_count` reads it for facilities and replaces `violation_count` for contingencies; an older cache is refused for it | `048d1d7` |
| `rank` dropped objects with no value | Question 8: the 82 ISLANDED contingencies, which have no loading, returned none | `rank` lists them after the ranked ones with value null, and counts them | `50fc80b` |
| Nothing said how to select tie lines | Questions 13, 14, and 18 took 18 to 26 minutes each; question 14 answered "no" from a query on an area named "Far West / West" | The tools and prompt say one `control_area` qualifier per area selects ties; a `tie` field and group; an area name no object has is refused | `c09c80a` |
| A name on a bus-number field matched nothing, silently | Question 12 matched "WALLER 1 1" against bus numbers | Refused with a pointer to `bus_name` | `c09c80a` |
| `read_file` could not join | Question 5: generation by area needed a script, after 18 minutes of reading every generator and bus | `read_file` joins tables by a key | `1021b89` |
| Scripts did not know where the files were | Questions 23 and 24: both scripts looked for the flat CSV at the top of `/run-data` | The description gives the sandbox's layout, limits, and index pattern; the result lists the files; a literal path that names nothing is flagged; the controller marks answers that used script output | `125acfe` |
| The sandbox image could not load pyarrow | Found while fixing the previous gap: `import pyarrow` failed as a normal user | The Dockerfile opens every file a normal user cannot read; the opt-in sandbox test imports pyarrow | `125acfe` |
| Confirmation was a prompt rule only | Question 22: the XML was replaced in the same turn it was asked | Destructive tools preview first, and act only on a confirmation in a later turn | `ff8305c` |
| Signed flows could be totaled across branches unflagged | The re-run's question 23: once ties were easy to select, −1,697.6 MW, a sum of flows in mixed directions, was given as the minimum net flow | `rank_groups` warns, and the controller notes, when it combines `p_from_mw` or `q_from_mvar` across branches; the prompt says to orient ties in a script | `a5e3a00` |

The re-run of the affected questions is reported in `agent_evaluation_gemma4_31b_fixes.md` and summarized in
`ai_planning_agent_verification.md`. Of its 13 prompts, 7 passed, 5 partly passed, and 1 failed, against 3,
6, and 4 before the fixes, and they took 44 minutes instead of 144.

Three problems remain. Question 12's model still states MVA headroom despite the prompt and the controller's
note. A qualifier on the circuit field `line_id` with a name still returns nothing, silently. And a
generated script can still exceed the sandbox's 1 GiB by loading the whole index at once.
