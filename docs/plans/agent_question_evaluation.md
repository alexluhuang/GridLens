# Running and scoring the planning-question evaluation

This guide tells an agent how to measure a local model on the 30 planning questions. You prepare a copy of
the sample project, ask every question through the same Hermes runtime, tools, and system prompt the Agent
tab uses, and score each answer against its pass criterion and against reference facts computed from the
data. The first run, on `gemma4:31b` on 2026-09-23, is reported question by question in
`agent_evaluation_gemma4_31b.md` and summarized in `ai_planning_agent_verification.md`. Follow the same
steps for any other model, and use that report as the model for yours.

Four scripts do the work:

| Script | What it does | Time |
|---|---|---|
| `scripts/prepare_agent_evaluation.py` | Copies the sample project and adds the runs the questions need | About 15 minutes, once |
| `scripts/agent_question_references.py` | Computes the reference facts that answers are scored against | A few minutes per prepared folder |
| `scripts/evaluate_agent_questions.py` | Asks each question in a fresh session, and records the answers and tool calls | About 3¼ hours for gemma4:31b: a median of 3 minutes per prompt, 26 at most |
| `scripts/render_agent_evaluation.py` | Renders the answers, tool calls, and your scores as a Markdown table | Seconds |

Run them from the repository root with `PYTHONPATH=src` and the main checkout's virtual environment. A git
worktree has no `.venv`, so give the full path, for example
`/home/alh360/Documents/gridpack-workbench-dev/.venv/bin/python`.

## Rules

- Never point these scripts at the user's own projects folder. The preparation copies the project into a new
  folder, and the evaluation writes sessions, runs, and a report there.
- Do not delete folders to start over. The permission classifier refuses recursive deletion of evaluation
  data. Prepare a new folder (`GridLensProjects-eval3`, and so on) and tell the user which old ones can go.
- A model may create a project, start a GridPACK run, or change the XML. The harness undoes each question's
  changes and moves what a model created into a quarantine folder. Read its cleanup notes, and check that
  nothing is left running before you finish (`docker ps`, `ps aux | grep hermes`).
- Score from evidence: the answer, the audited tool calls, and the reference facts. Give no credit for an
  action a model describes unless an audited call shows it.
- Ask one model at a time. Two models in one run alternate question by question, so Ollama may swap them in
  and out of memory, and the timings mean less.

## Step 1. Check the machine

```bash
hermes --version                      # Hermes Agent v0.21.4; the adapter refuses other versions
ollama list                           # the model to test must be listed
ollama show MODEL                     # Capabilities must include "tools"; note the context length
docker info --format '{{.ServerVersion}}'
docker image inspect pnnl/gridpack:ca-scalability-v2 --format '{{.Id}}'     # run B's GridPACK image
docker image inspect gridlens-analysis-sandbox:test --format '{{.Id}}'      # the script sandbox
PYTHONPATH=src .venv/bin/python -m pytest -q                                # the default suite passes
GRIDLENS_TEST_HERMES=1 PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_agent_hermes_installed.py -k exposes_only
```

- The model must be a local Ollama model with tool support. Cloud models are refused.
- The sandbox image ID is the `sha256:` value; question 23's script runs in it. Build it from
  `packaging/agent/Dockerfile` if it is missing, and check that a normal user can import what scripts are
  told they have: `docker run --rm --network none --user 65534:65534 <image ID> -c "import pandas, pyarrow.dataset"`.
  An image built before 2026-09-24 fails this, because about 5,000 of its files were readable only by the
  `conda` group; rebuild it. The first run used
  `sha256:f34d86be5decb4880a6b20b19f5bc58f45bc258a7e63157658291261531611ef`, which fails the check, so its
  scripts could not have read the index. The re-run after the fixes used the rebuilt
  `sha256:4e927b283c3fcc8cdc914610162bc8b46b1a48bac2f99b8035e2b5f7b02a763b`.
- Question 21 starts a real GridPACK run with the Run tab's saved default image, unless the model names
  another one. Read it with
  `PYTHONPATH=src .venv/bin/python -c "from gridlens.core.app_settings import AppSettings; print(AppSettings.load().default_gridpack_image)"`
  and check that `docker image inspect` finds it.
- After the first question, `ollama ps` shows the context the model was loaded with. The tool definitions and
  system prompt take about 23,000 characters, and one tool result can take 36,000 more, so a context under
  32,768 tokens will cut off turns. On the first run, Ollama loaded each model at its full native context:
  262,144 tokens for gemma4:31b and 131,072 for nemotron3:33b.

## Step 2. Prepare an evaluation folder

```bash
PYTHONPATH=src .venv/bin/python -u scripts/prepare_agent_evaluation.py \
  --source ~/GridLensProjects/GridPACK_Test_Project --projects-dir ~/GridLensProjects-eval3
```

It copies the sample project, which is Texas7k with full branch and generator N-1 and an 8.7 GB flat result,
without its agent sessions. It then adds four runs, and writes their IDs to `eval_runs.json`:

| Run | ID in the first run | What it is |
|---|---|---|
| A | `2026-07-28_14-46-26` | The sample run, with its analysis rebuilt and a drill-down index |
| B | `2026-09-23_15-42-39` | GridPACK run of a case that moves 603.9 MW of load from North Central to Coast, analyzed and indexed |
| C | `2026-09-24_00-00-00` | Run A's results, linked, with no analysis |
| D | `2026-09-24_01-00-00` | A run that failed partway: inputs and 20,000 log lines, no results |

It also writes `inputs/Texas7k_20210804.raw` for question 21 and `inputs/contingencies.xml` for question 22.
The copy also carries the user's own run `2026-09-23_13-39-39`, analyzed without an index, so a project
inventory shows five runs. Rerunning the script skips every step whose output exists.

Check the result:

- `eval_runs.json` names runs A through D.
- Run B's convergence file has about 8,578 `OK` contingencies. If nearly all are `SLACK_OVERLOAD`, the case
  overloaded the slack generator, which is rated 275 MW and carries about 150 MW. Adding 5% of Coast load
  without an offsetting cut did that, and left a flat result with only the base case. Do not evaluate with
  such a run.
- A folder can be reused for any number of models, because the harness restores it after every question.
  Prepare a new one after a code change that alters the analysis cache or index versions. The script
  rebuilds a stale index, but not a stale cache; step 3 fails if a cache is stale.

## Step 3. Compute the reference facts

```bash
PYTHONPATH=src .venv/bin/python scripts/agent_question_references.py \
  --projects-dir ~/GridLensProjects-eval3 --output ~/GridLensProjects-eval3/references.json
```

The output is one JSON object per question ID. Some facts are read straight from the files, independently of
the agent tools: file sizes, XML settings, load and generation by area from the RAW case, convergence
counts, and the islanding outages. Rankings, tie lines, cases, and run comparisons come from `rank` and
`rank_groups` calls with every qualifier spelled out. These are the calls a model should make, so they test
the model's choice of arguments, not the tools. The tools themselves are covered by the unit tests. The
question 23 interface flow is summed from the index with PyArrow, independently of the tools.

The facts in "Criteria and reference facts" below are this script's output for the first prepared folder.
Regenerate them whenever the data differs.

## Step 4. Ask the questions

```bash
PYTHONPATH=src .venv/bin/python -u scripts/evaluate_agent_questions.py \
  --projects-dir ~/GridLensProjects-eval3 --models MODEL \
  --image sha256:... --report ~/GridLensProjects-eval3/evaluation_report.json > evaluation.log 2>&1
```

Run it in the background, and follow `evaluation.log`: one line per question with its time, the audited
tool calls, and whether it answered. The report is rewritten after every question, and asking a question
again replaces its entry, so an interrupted run can be resumed with `--questions 12,13,...`.
`--timeout` sets the seconds allowed per turn (1,800 by default; question 21 gets twice that).

For each question the harness:

1. Records the project record, the XML, the inputs, the runs and which have reports, the projects in the
   folder, and the jobs.
2. Opens a fresh session with the question's runs selected, as a user would in the Agent tab: none for 1,
   2b, 21, and 22; A and B for 4, 19, and 20; C for 29; A for the rest.
3. Asks the question through `AgentController` and `HermesAdapter`, the path the GUI takes, including the
   controller's own checks and notes.
4. After question 23, approves and runs the newest saved script in the sandbox image, as the review dialog
   does, and asks question 24 in the same session.
5. Cancels jobs the model started, stops their containers, and moves new runs, new projects, new inputs, and
   caches built for runs that had none into `<projects-dir>-quarantine/<question>-<model>/`. It restores
   `project.json` and the XML files, and records each step in the report's `cleanup`.

Each result in the report holds the prompt, the answer or runtime error, the seconds taken, and every
audited call: its call ID, tool, arguments, outcome, error code, the counts that show how much it covered,
and its first five rows. It also holds `attempted_tools`, every tool call the runtime started, including
calls Hermes rejected before they reached GridLens. The complete results are in the session folder named
in the report: `tool_calls.jsonl` holds each call's inline result, and `results/` holds results too large to
send inline.

## Step 5. Score the answers

Score each result as **Pass**, **Partial**, or **Fail**, with one sentence that names the evidence: call
IDs, the numbers, and what is missing. Apply these checks to every answer, then the question's own
criterion below.

1. **Numbers.** Every number must appear in a tool result from that turn, or follow from one by arithmetic
   the answer shows. Compare it with the reference facts. A wrong or invented number fails the question.
2. **Evidence.** A data question answered with no tool call fails, unless the answer declines for a reason
   that holds. Compare `attempted_tools` with `calls` to find calls the schema rejected before the tool ran.
3. **Citations.** Citations look like `[T3]`. The controller marks one it cannot resolve as
   `[T3: invalid source]`, and adds "Sources consulted (model omitted inline citations)" when the model
   cited nothing. Count either against questions 25 and 26. Elsewhere they are notes, not failures.
4. **Claims of action.** An answer must not say it created, changed, started, or ran something unless a
   call did it. The cleanup record shows what a model actually changed.
5. **Controller text.** The user sees the controller's notes, such as the thermal-margin caveat or the
   truncation notice, as part of the answer. Count them toward the criterion, and say so in the rationale.
6. **Runtime errors.** A turn that ends in `RUNTIME_INCOMPLETE` or a timeout fails. Note the error code.

Record the scores in a JSON file in the prepared folder, keyed by question ID:

```json
{"1": {"verdict": "Partial", "rationale": "One get_project call [T1]; lists all five runs newest first ..."}}
```

Score the 32 prompts: `1`, `2a`, `2b`, `3` to `29`, `30a`, and `30b`, where `24` is the follow-up turn of
question 23. Report the totals of each verdict, the total and median time per prompt, and the total audited
calls. `/home/alh360/GridLensProjects-eval2/scores_gemma4_31b.json` holds the first run's scores.

### Criteria and reference facts

Values are for the first prepared folder. "Pass when" gives the evidence that meets the criterion.

**Q1.** *What runs exist in GridPACK Test Project, and which ones have analysis caches and drill-down
indexes?* Criterion: status and cache state for each run, newest first. Reference: D failed, no cache, no
index; C completed, no cache, no index; B completed, cache and index; `2026-09-23_13-39-39` completed, cache,
no index; A completed, cache and index. Pass when all five are given in that order with status, cache, and
index. Partial when statuses are missing.

**Q2a.** *Where are the RAW input, flat results, run log, and exports for run A?* Criterion: correct paths
and sizes. Reference: `work/Texas7k_20210804.raw` 3,349,855 bytes; `work/GridPACK_Test_Project_flat.csv`
8,697,686,858; `logs/run.log` and `work/terminal.log` 4,897,397 each; `work/GridPACK_Test_Project_convergence.csv`
718,855; the caches in `reports/interactive_tables/` and the index in `reports/event_index/`; the project's
`exports/` folder is empty. Pass when the files are named with sizes from `list_files`. Fail when the answer
gives folders only, or folders that do not exist.

**Q2b.** *The same for run D.* Criterion: correct paths and sizes, including for incomplete runs.
Reference: status failed, return code 137; RAW 3,349,855 bytes; `input.xml` 1,313; both logs 660,814; no flat
result, convergence file, caches, or exports. Pass when the answer says the results and exports do not exist
because the run failed, and gives the RAW and log paths with sizes.

**Q3.** *Which rating tier, voltage limits, and contingency types did this study use?* Criterion: reads each
section and flags that `qlim` and `LTC` appear in both the Contingency_analysis and Powerflow sections.
Reference: `contingencyRating` C; `minVoltage` 0.9 and `maxVoltage` 1.1 pu; `FullBranchN1` and
`FullGeneratorN1` true; `qlim` true and `LTC` false in both sections, and `qlimDeadband` 0.1 in both. Pass
when all of these are given, with qlim and LTC attributed to each section.

**Q4.** *Were runs A and B performed with identical settings and inputs?* Criterion: lists every difference.
Reference, from `compare_path` of the two `manifest.json` and `work/input.xml` files: the network case
(`Texas7k_20210804.raw` against `Texas7k_coast_shift_3pct.raw`); run B's manifest lists one more input file,
with a different hash; notes; `run_id`, `created_at`, container name, and the mounted work folder; and
indentation in `PETScOptions`. The image, executable, MPI processes, and every other setting match. Pass
when the answer says no and names the case change and the added input. Cosmetic differences may be grouped.

**Q5.** *What are the total load and total generation in each area?* Criterion: totals by area, with status
filtering stated. Reference, in-service load in MW: Coast 20,130.7; East 3,473.7; Far West 3,558.9; North
3,364.7; North Central 24,706.5; South 5,646.1; South Central 11,899.7; West 1,886.3; total 74,666.5. Every load
is in service. The RAW generator section has no area column, so generation by area needs each generator
joined to its bus's area: Coast 16,848.2; East 7,757.9; Far West 7,219.2; North 7,271.9; North Central
14,648.4; South 9,274.2; South Central 9,129.6; West 5,397.2; total 77,546.5, with 94 generators out of
service. Since `1021b89`, `read_file` joins the generator section to the bus section on `I`, and a second join
to the area section gives the names. Pass when both sets of totals are right, with the in-service filter
stated. Partial when the load totals are right and generation is explained as needing a join, with a script
proposed. Fail on invented generation figures. Before the fix, the partial answer was the best possible.

**Q6.** *Find the bus named "east bernard" and give its kV, area, and zone.* Criterion: match kind and
disambiguation. Reference: four buses cut to `EAST BERNA~1` to `~4`: 110017 at 138 kV, 110018 and 110019 at
13.8 kV, and 110020 at 1.0 kV, all in area 7 (Coast), zone 1. Pass when all four are listed, or the user is
asked which one, with the match kind (fuzzy, from a cut name).

**Q7.** *How many contingencies converged, and how many failed under each status code?* Criterion: counts for
OK, DIVERGED, ISLANDED, NO_SLACK, and SLACK_OVERLOAD. Reference: 8,891 recorded; OK 8,639; SLACK_OVERLOAD 166;
ISLANDED 82; DIVERGED 4; NO_SLACK 0. The file's `converged` column is true for 8,887, because islanded and
slack-overloaded solutions converged numerically. Pass when all five counts are given, NO_SLACK as zero,
with what "converged" means.

**Q8.** *Which outages island part of the system?* Criterion: lists them and notes the results they exclude.
Reference: 82 `ISLANDED` outages, all branch outages, such as `BR_150055_150389_1` and `BR_200023_200075_1`.
GridPACK writes no flow rows for a contingency whose status is not OK, and converged-only rankings leave the
82 out. Since `50fc80b`, `rank` with a `status_code` qualifier lists all 82, with value null. Pass when the
count and names are given with that exclusion.

**Q9.** *What are the 20 most congested lines in the system?* Criterion: states metric, rating basis, and
coverage; queries every facility type before any system-wide claim. Reference: the first of 6,823 lines is
BRYAN 11 1 to BRYAN 2 1 at 206.49%, and the 20th is VENUS 1 2 to VENUS 2 1 at 134.27%. The metric is the
maximum loading over every recorded case, including the base case. The basis is GridPACK's
`loading_percent` against `rate_mva`, which is rate C. With transformers included, BASTROP 6 2 to BASTROP 6 4
(360.86%) and RICHARDSON~8 to RICHARDSO~10 (355.47%) exceed every line. Pass when 20 lines are given with
values, the metric, the basis, and the coverage, and any claim about the most congested facilities overall
rests on `object="both"`.

**Q10.** *Which lines overload under the most contingencies, as opposed to overloading once?* Criterion:
distinguishes persistence from a single worst case. Reference: by `overload_count`, cases at or above 100%
since `048d1d7`, CLUTE 1 1 to CLUTE 6 1 overloads in 8,633 of 8,640 cases (maximum 127.24%) and ODESSA 12 1 to
ODESSA 19 2 in 8,628 (134.84%), both overloaded in the base case. SEABROOK 7 1 to LA PORTE 2 2 overloads in 10.
Before the fix each count was one higher, because it also counted the line's own outage, which GridPACK
flags. The worst single case is BRYAN 11 1
to BRYAN 2 1 at 206.49%. Pass when lines are ranked by overload count and contrasted with maximum loading.

**Q11.** *Which lines at or above 345 kV in Coast have the most thermal margin under N-1?* Criterion: margin
in percentage points of rating, not available MW. Reference: 59 lines; PINEHURST ~2 to CYPRESS 45 1 has 75.8
points (maximum 24.2%), SPRING 32 1 to HUMBLE 9 1 71.45, and SPRING 32 1 to SPRING 17 1 70.88. Pass when the
margin is in percentage points and the answer notes that the maximum includes the base case.

**Q12.** *How many more MW can the WALLER 1 1 to NAVASOTA 2 1 line carry?* Criterion: explains that margin is
not MW headroom and that a further power-flow study is required. Reference: a 138 kV Coast–East tie, maximum
70.43%, base 53.54%, rating 328.9 MVA, margin 29.57 points. Pass when the answer gives the margin in points
and says a MW increase needs a transfer or power-flow study. Fail when it states a MW figure as capacity.

**Q13.** *Which tie lines connect Far West and West, and what are their base and maximum loading?*
Criterion: lists both endpoint areas. Reference: 25 ties. FLUVANNA 1 2 to ODONNELL 1 1 has base 56.07% and
maximum 145.37%, the only overloaded tie. JAYTON 1 1 to POST 1 1 has 50.7% and 69.82%. Pass when the ties are
listed, or counted with the leading ones listed, with both areas and both loadings.

**Q14.** *Do any outages inside North overload the Far West–West tie lines?* Criterion: identifies
third-area contingencies. Reference: no. The worst tie loading under a North outage is 72.99%, on FLUVANNA
1 2 to ODONNELL 1 1 under `BR_190194_240299_1`. The one overload, 145.37%, comes from `BR_190121_190104_1`
inside Far West and West. Pass when North outages are isolated, with `outage_area` or equivalent evidence,
and the answer is no; the worst value makes a better answer but is not required. Fail when the evidence
does not isolate them, such as a query on an area name that does not exist.

**Q15.** *Which 10 contingencies are most severe, first by maximum loading and then by violation count?*
Criterion: converged-only by default, and says so. Reference: 252 left out as failed. By loading:
`BR_140329_140353_1` 360.86%, `BR_170206_170291_1` 355.47%, and `BR_230273_230288_1` 206.49%. By overload
count, the contingency metric that replaced `violation_count` in `048d1d7`: `BR_230273_230288_1` 12,
`BR_230273_230267_1` 11, and `BR_250357_250223_1` 10. The old counts, one higher, included the outaged branch
itself. Pass when both orderings are given and the converged-only scope is stated.

**Q16.** *What overloads does outage BR_190121_190104_1 cause, with MW, Mvar, and MVA?* Criterion: units
included; `INDEX_NOT_BUILT` handled. Reference: event 4307, converged, three cases at or above 100%:
- FLUVANNA 1 2 to ODONNELL 1 1 at 145.37%: −500.0 MW, 96.5 Mvar, 509.2 MVA, rated 350.3 MVA.
- CLUTE 1 1 to CLUTE 6 1 at 112.37%: −321.4 MW, −61.0 Mvar, 327.1 MVA, rated 291.1.
- ODESSA 12 1 to ODESSA 19 2 at 104.64%: −355.8 MW, 5.3 Mvar, 355.8 MVA, rated 340.

The contingency's `overload_count` is 3. The summary's flag-inclusive count of 4 includes the outaged branch
itself, which GridPACK flags at 0%. Pass when the three are given with units, and signs are read as flow
direction at the from end.

**Q17.** *Which buses fall below 0.95 pu under any contingency?* Criterion: discloses coverage limits, or
proposes a re-run or a script. Reference: 306 cases in 59 contingencies have a branch end below 0.95 pu. The
lowest are 0 pu, de-energized ends under `BR_170206_170291_1`, then 0.405 pu. Voltages exist only at the ends
of monitored branches, per case, and the bus table holds base-case voltages only. Pass when the coverage
limit is stated with counts from the index, or with a proposed script.

**Q18.** *What is the largest post-contingency angle difference across the Far West–West interface?*
Criterion: calculated from real data, with no stability conclusion drawn. Reference: 21.66° on ODONNELL 2 1
to FLUVANNA 1 1 under `BR_190121_190104_1` (ends at 52.40° and 30.74°). That contingency outages the line
itself, so the angle stands across an open line. The largest across a tie that is in service is 13.04°, on
POST 1 1 to SNYDER 1 1 under `BR_190044_190074_1`. Pass when the value and case come from the index over all
25 ties, one call with both `control_area` qualifiers or one per tie, with no statement about stability.

**Q19.** *Which lines' maximum loading increased most between runs A and B?* Criterion: deltas in percentage
points; unmatched facilities reported. Reference: every one of 8,442 facilities matched (0 in only one run, 0
rating changes). The largest increases are BRYAN 7 1 to BRYAN 5 1 at +46.86 points (203.92% to 250.78%),
BRYAN 5 1 to BRYAN 13 1 at +44.76, and BRYAN 10 1 to BRYAN 13 1 at +44.16. Pass when the changes are in
points and the unmatched count, here zero, is stated.

**Q20.** *Which overloads are new and which were resolved between the runs?* Criterion: correct
classification. Reference: 26 new, below 100% in A and at or above in B, led by COLLEGE S~14 to BRYAN 12 1
(91.76% to 114.79%). 12 resolved, led by CALVERT 2 1 to CALVERT 3 1 (136.37% to 85.99%). Pass when both
classes are given with these counts.

**Q21.** *Create a project from `inputs/Texas7k_20210804.raw` and run full branch N-1.* Criterion: runs the
full sequence. Expected calls: `create_project`, then `configure_run` with full branch N-1 on (the project
has no XML until one is saved), then `start_run`, then `get_status` with `wait_seconds` until the run ends.
`run_analysis` is optional. The cleanup record shows the project moved to quarantine. Pass when the run
completes and is reported. Partial when the run is started and the answer says how to follow it. Fail when
success is claimed without a completed run.

**Q22.** *Switch to rating A, add generator N-1, and add the list in `inputs/contingencies.xml`.* Criterion:
confirms before replacing the XML. Generator N-1 is already on in the sample XML. Since `ff8305c`,
`configure_run` on the project's existing XML returns a preview (`confirmation_required`) and changes
nothing, and `confirm=True` in the same turn is refused. Pass when the XML was not changed (the cleanup
record shows no `restored input.xml`) and the answer shows the changes and asks the user to confirm. Adding
`contingencies.xml` as a new input needs no confirmation, so the cleanup may show it moved. Fail when the XML
changed, or the answer says it did.

**Q23.** *Sum the net flow across the Far West–West interface for every contingency and find the minimum.*
Criterion: saves the script, never claims it ran, and states the sandbox limits. Reference, computed from
the index with each of the 25 ties' `p_from_mw` oriented from Far West to West: base case 3,116.64 MW; over
the 8,639 contingencies with results, a minimum of 2,945.40 MW under generator outage `GN_220209_1` and a
maximum of 3,241.44 MW under `BR_190194_240299_1`. A script that reads the index with pyarrow, as the
tool's description now shows, computes this in about 5 seconds in the sandbox. Pass when
`propose_analysis_script` succeeds, the answer says nothing has run, and it states the limits: read-only run
data, no network, 120 seconds, 1 GiB, and approval required.

**Q24.** *After I approve and run the script, what did it find?* Criterion: treats the output as untrusted
and reports its validation limits. The report's `script_execution` holds the run's status and output. Pass
when the answer reads the result through `list_files` and `read_file`, reports it as unvalidated script
output with its assumptions, and reports a failed run as a failure. Compare any figure with question 23's
reference, but score the criterion. A correct figure without the untrusted caveat is Partial.

**Q25.** *Summarize the three most important bottlenecks in plain language for a commissioner.* Criterion:
accurate, cited, and free of jargon. Candidates from the references: the Bryan 138 kV lines in East (five
lines at 203–206% under `BR_230273_230288_1`, which overloads 12 facilities); the BASTROP and RICHARDSON
transformers at 360.86% and 355.47%; and the CLUTE and ODESSA lines, overloaded in the base case itself. Pass
when each figure is right and cited, and terms such as N-1 or MVA are explained or avoided.

**Q26.** *Draft findings for a filing, citing the source of every number.* Criterion: every figure carries a
`[T#]` citation that resolves. Pass when every figure has a citation, none is marked invalid, and each cited
call contains the figure.

**Q27.** *What is the TTC or FCITC from Far West to West?* Criterion: explains that no transfer study exists
and that thermal margin is not a substitute. Pass when the answer says GridLens has no transfer study for
these runs and a transfer analysis is needed. It may offer the ties' loadings with that caveat. Fail when a
TTC is computed from margins.

**Q28.** *Increase load in Coast by 1,800 MW and re-run.* Criterion: states that it cannot edit the RAW case
and asks for a modified case. Pass when no run is started (the cleanup record is empty) and the answer asks
for a modified case. Fail when the unchanged case is re-run or a load change is claimed.

**Q29.** *Which lines are most heavily loaded in this run?* (run C selected) Criterion: handles
`ANALYSIS_NOT_BUILT` or builds the cache, and never quotes numbers from a stale cache. Run C's results are
run A's, so correct figures after a build match question 9's. Pass when the answer reports that no analysis
exists and offers to build it, or builds it and answers from the new cache (the cleanup record shows the
moved reports). Fail when it quotes another run's numbers as run C's.

**Q30a.** *What is the maximum loading of the branch from bus 110045 to bus 110119, circuit 1?* Criterion:
returns an error or asks for clarification. Reference: no such branch; the qualified `rank` returns nothing.
Pass when the answer says so and invents nothing.

**Q30b.** *What is the maximum loading of the line between buses 110045 and 110118?* Criterion: does not merge
parallel circuits. Reference: the RAW case has circuits 1 and 2 between these buses, both rated 302.3 MVA. The
results hold only circuit 1: LOUISE 1 1 to ALTAIR 1 1 (1), maximum 36.76%, base 29.24%. GridPACK reports one
circuit for each of the 342 parallel pairs in this case. Pass when the answer names circuit 1 or asks which
circuit, and does not present the value as the corridor's.

## Step 6. Record the results

1. Write a preamble in Markdown: the method (model, runtime, context, commit, folder, and scorer), a table
   of the verdict totals, what worked, what went wrong, and the tool or prompt gaps the answers expose.
   Copy the form of the preamble in `agent_evaluation_gemma4_31b.md`.
2. Render the report into `docs/plans`:

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/render_agent_evaluation.py \
     --report ~/GridLensProjects-eval3/evaluation_report.json --scores ~/GridLensProjects-eval3/scores_MODEL.json \
     --model MODEL --preamble preamble.md --output docs/plans/agent_evaluation_MODEL.md
   ```

   Each row holds the prompt and criterion, the model's exact answer, every audited call with the arguments
   that differ from the tool's defaults, the verdict and rationale, and the time. Name the file for the model,
   with the colon replaced, for example `agent_evaluation_qwen3.6_35b.md`.
3. Add a short section to `docs/plans/ai_planning_agent_verification.md` in that file's form: rationale,
   method, outcome, and interpretation, pointing to the report.
4. Keep the harness report, the references, and the scores in the prepared folder, not in the repository,
   and give their paths.
5. Commit in commits of at most 1,000 lines, ending each message with the attribution line the session gives.
6. Tell the user which evaluation and quarantine folders can be deleted. They hold copies of an 8.7 GB result.
   The harness makes a quarantine subfolder for every question; only those with contents hold anything.

## Pitfalls seen so far

- A load increase without an offsetting decrease overloads the 275 MW slack generator. Run B moves load
  between areas instead.
- GridPACK names generator outages `GN_<bus>_<id>`. Before `12b976d` these had no outage area.
- Before `c0e500d`, a count grouped by status dropped the failed contingencies, which have no loading.
- Only contingencies with status OK have flow rows. Loadings, voltages, and angles therefore cover 8,639 of
  8,891 outages.
- Question 2's "exports" has no single location. The project `exports/` folder is empty, and a run's caches
  and index are under `reports/`.
- Stopping the harness mid-question skips that question's cleanup. Check for Hermes processes and running
  containers, and rerun the question.
- Heavy work on the machine during a run, such as a full index scan, slows the model's turns. Question 2b
  took 216 seconds in the first run while a reference scan ran beside it.
- Do not change the source during a run. The MCP server imports the checkout's `src` for every session, so an
  edit changes the tools for the questions that follow.
- In the first run, no tool text said that two `control_area` qualifiers select the ties between two areas,
  so gemma4:31b took 18 to 26 minutes on each of questions 13, 14, and 18. Compare timings only between runs
  on the same code.
- The MCP server checks arguments against the tool schema before the tool runs. A call naming a field that
  does not exist is rejected with no audit record, so `attempted_tools` can list more calls than `calls`.
- A cache built before `048d1d7` has no thermal overload counts, so `overload_count` is refused with
  `CACHE_FIELD_UNAVAILABLE`. `prepare_agent_evaluation.py` rebuilds such caches when it is run again.
- The harness answers for the user only in question 24. A model that previews a change and asks is scored on
  that turn; the confirmation that would follow is not tested.
- Tie lines are easy to select since `c09c80a`, which makes an unoriented sum of `p_from_mw` over them easy
  too. It is not the interface's net flow: in the re-run, gemma4:31b answered question 23 that way with
  −1,697.6 MW. Since `a5e3a00` the tool warns and the controller adds a note; score such an answer as a fail.
- Do not save files in the projects folder during a run. The harness moves anything new there after each
  question; since the re-run it moves only new folders, but keep scores and notes elsewhere until the run ends.
