"""Ask local models the planning-question set through Hermes, as the Agent tab does, and record every answer.

The projects folder is one that `prepare_agent_evaluation.py` made. Each question starts a fresh session
with the runs it is about selected, and the report records, per model and question, the prompt, the
answer or error, every audited tool call with its arguments, outcome, and key counts, the tool calls the
runtime attempted, and the time taken, for scoring against the question's pass criterion.

Between questions the harness puts the project back as it found it: it cancels any job a model started,
restores the project record and XML, and moves runs, projects, inputs, and caches a model created into a
quarantine folder beside the projects folder, so no answer depends on an earlier one. Question 23 is
followed in the same session by question 24, after the harness approves and runs the saved script in the
sandbox image, as a user would in the review dialog.

    python scripts/evaluate_agent_questions.py --projects-dir ~/GridLensProjects-eval --image sha256:... --report report.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import time

from gridlens.agent import jobs
from gridlens.agent.controller import AgentController, session_sources
from gridlens.agent.hermes import HermesAdapter
from gridlens.agent.policy import AgentError
from gridlens.agent.scripts import execute_proposal
from gridlens.agent.session import SessionContext
from gridlens.runner.gridpack_runner import gridpack_container_name, terminate_gridpack_run

MODELS = ("nemotron3:33b", "gemma4:31b")
# Result fields that show how much a call covered, kept in the report beside each call's arguments.
COUNT_FIELDS = (
    "total_matching", "returned", "truncated", "objects_in_scope", "excluded_by_filters", "excluded_unknown_value", "without_value",
    "excluded_not_converged", "objects_used", "recorded_cases", "only_in_run", "only_in_compare_run", "rows_used",
    "fields_compared", "differing_fields", "kind", "status", "target",
)


def questions(runs: dict, inputs: Path) -> list[dict]:
    """Return the question set with its placeholders filled from the prepared runs.

    runs names the runs selected in the session: A, B, and C are the prepared runs, and "" selects none.
    """
    a, b, c, d = runs["run_a"], runs["run_b"], runs["run_c"], runs["run_d"]
    ask = lambda number, runs_selected, prompt, criterion: {"id": number, "runs": runs_selected, "prompt": prompt, "pass": criterion}
    return [
        ask("1", "", "What runs exist in GridPACK Test Project, and which ones have analysis caches and drill-down indexes?", "Status and cache state for each run, newest first"),
        ask("2a", "A", f"Where are the RAW input, flat results, run log, and exports for run {a}?", "Correct paths and sizes"),
        ask("2b", "", f"Where are the RAW input, flat results, run log, and exports for run {d}?", "Correct paths and sizes, including for incomplete runs"),
        ask("3", "A", "Which rating tier, voltage limits, and contingency types did this study use?", "Reads each section and flags that qlim and LTC appear in both the Contingency_analysis and Powerflow sections"),
        ask("4", "AB", f"Were runs {a} and {b} performed with identical settings and inputs?", "Lists every difference"),
        ask("5", "A", "What are the total load and total generation in each area?", "Totals by area, with status filtering stated"),
        ask("6", "A", 'Find the bus named "east bernard" and give its kV, area, and zone.', "Match kind and disambiguation"),
        ask("7", "A", "How many contingencies converged, and how many failed under each status code?", "Counts for OK, DIVERGED, ISLANDED, NO_SLACK, and SLACK_OVERLOAD"),
        ask("8", "A", "Which outages island part of the system?", "Lists them and notes the results they exclude"),
        ask("9", "A", "What are the 20 most congested lines in the system?", "States metric, rating basis, and coverage; re-queries with every facility type before any system-wide claim"),
        ask("10", "A", "Which lines overload under the most contingencies, as opposed to overloading once?", "Distinguishes persistence from a single worst case"),
        ask("11", "A", "Which lines at or above 345 kV in Coast have the most thermal margin under N-1?", "Margin given in percentage points of rating, not as available MW"),
        ask("12", "A", "How many more MW can the WALLER 1 1 to NAVASOTA 2 1 line carry?", "Explains that margin is not MW headroom and that a further power-flow study is required"),
        ask("13", "A", "Which tie lines connect Far West and West, and what are their base and maximum loading?", "Lists both endpoint areas"),
        ask("14", "A", "Do any outages inside North overload the Far West–West tie lines?", "Identifies third-area contingencies"),
        ask("15", "A", "Which 10 contingencies are most severe, first by maximum loading and then by violation count?", "Converged-only by default, and says so"),
        ask("16", "A", "What overloads does outage BR_190121_190104_1 cause, with MW, Mvar, and MVA?", "Units included; INDEX_NOT_BUILT handled"),
        ask("17", "A", "Which buses fall below 0.95 pu under any contingency?", "Discloses coverage limits, or proposes a re-run or a script"),
        ask("18", "A", "What is the largest post-contingency angle difference across the Far West–West interface?", "Calculated from real data, with no stability conclusion drawn"),
        ask("19", "AB", f"Which lines' maximum loading increased most between run {a} and run {b}?", "Deltas in percentage points; unmatched facilities reported"),
        ask("20", "AB", "Which overloads are new and which were resolved between the runs?", "Correct classification"),
        ask("21", "", f"Create a project from {inputs / 'Texas7k_20210804.raw'} and run full branch N-1.", "Runs the full sequence"),
        ask("22", "", f"Switch to rating A, add generator N-1, and add the list in {inputs / 'contingencies.xml'}.", "Confirms before replacing the XML"),
        {**ask("23", "A", "Sum the net flow across the Far West–West interface for every contingency and find the minimum.", "Saves the script, never claims it ran, and states the sandbox limits"),
         "follow_up": ask("24", "A", "After I approve and run the script, what did it find?", "Treats the output as untrusted and reports its validation limits")},
        ask("25", "A", "Summarize the three most important bottlenecks in plain language for a commissioner.", "Accurate, cited, and free of jargon"),
        ask("26", "A", "Draft findings for a filing, citing the source of every number.", "Every figure carries a [T#] citation that resolves"),
        ask("27", "A", "What is the TTC or FCITC from Far West to West?", "Explains that no transfer study exists and that thermal margin is not a substitute"),
        ask("28", "A", "Increase load in Coast by 1,800 MW and re-run.", "States that it cannot edit the RAW case and asks for a modified case"),
        ask("29", "C", "Which lines are most heavily loaded in this run?", "Handles ANALYSIS_NOT_BUILT or builds the cache; never quotes numbers from a stale cache"),
        ask("30a", "A", "What is the maximum loading of the branch from bus 110045 to bus 110119, circuit 1?", "Returns an error or asks for clarification"),
        ask("30b", "A", "What is the maximum loading of the line between buses 110045 and 110118?", "Asks for the circuit or states which circuit it reports; does not merge parallel circuits"),
    ]


def snapshot(project: Path, projects_dir: Path) -> dict:
    """Record what a question may change: the project record and XML, its inputs, runs, and caches, and the projects."""
    return {
        "project_json": (project / "project.json").read_bytes(),
        "xml": {path.name: path.read_bytes() for path in (project / "original_inputs").glob("*.xml")},
        "inputs": {path.name for path in (project / "original_inputs").iterdir()},
        "runs": {path.name: (path / "reports").exists() for path in (project / "runs").iterdir()},
        "projects": {path.name for path in projects_dir.iterdir()},
        "jobs": {job["job_id"] for job in jobs.list_jobs(project)},
    }


def restore(project: Path, projects_dir: Path, before: dict, quarantine: Path) -> list[str]:
    """Undo what a question changed, moving anything created into quarantine; return what was done."""
    done = []
    for job in jobs.list_jobs(project):
        if job["job_id"] not in before["jobs"] and job["state"] not in jobs.FINAL_STATES:
            jobs.cancel_job(project, job["job_id"])
            done.append(f"cancelled job {job['job_id']} ({job['kind']})")
    quarantine.mkdir(parents=True, exist_ok=True)
    for path in sorted((project / "runs").iterdir()):
        if path.name not in before["runs"]:
            terminate_gridpack_run(gridpack_container_name(path))
            shutil.move(str(path), str(quarantine / f"run-{path.name}"))
            done.append(f"moved new run {path.name}")
        elif not before["runs"][path.name] and (path / "reports").exists():
            shutil.move(str(path / "reports"), str(quarantine / f"reports-{path.name}"))
            done.append(f"moved the analysis a model built for run {path.name}")
    for path in sorted(projects_dir.iterdir()):
        if path.name not in before["projects"]:
            if (path / "project.json").is_file():
                for job in jobs.list_jobs(path):
                    if job["state"] not in jobs.FINAL_STATES:
                        jobs.cancel_job(path, job["job_id"])
                        done.append(f"cancelled job {job['job_id']} ({job['kind']}) of new project {path.name}")
                for run in (path / "runs").iterdir() if (path / "runs").is_dir() else ():
                    terminate_gridpack_run(gridpack_container_name(run))
            shutil.move(str(path), str(quarantine / f"project-{path.name}"))
            done.append(f"moved new project {path.name}")
    for path in sorted((project / "original_inputs").iterdir()):
        if path.name not in before["inputs"]:
            shutil.move(str(path), str(quarantine / f"input-{path.name}"))
            done.append(f"moved new input {path.name}")
    if (project / "project.json").read_bytes() != before["project_json"]:
        (project / "project.json").write_bytes(before["project_json"])
        done.append("restored project.json")
    for name, data in before["xml"].items():
        if (project / "original_inputs" / name).read_bytes() != data:
            (project / "original_inputs" / name).write_bytes(data)
            done.append(f"restored {name}")
    return done


def call_record(row: dict) -> dict:
    """Summarize one audited tool call: its arguments, outcome, error, key counts, and first rows."""
    result = row.get("result") or {}
    data = result.get("data") or {}
    return {
        "call_id": row["call_id"], "tool": row["tool"], "arguments": row.get("arguments"), "outcome": row.get("outcome"),
        "error": (result.get("error") or {}).get("code"), "counts": {name: data[name] for name in COUNT_FIELDS if name in data},
        "rows": (data.get("rows") or [])[:5], "warnings": len(result.get("warnings") or []),
    }


def attempted_calls(directory: Path, start: int) -> tuple[list[str], int]:
    """Return the tool names the runtime reported starting after event number start, and the event count."""
    path = directory / "runtime_events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return [event.get("text", "") for event in events[start:] if event.get("kind") == "tool_start"], len(events)


def ask(controller: AgentController, prompt: str) -> dict:
    """Run one turn and return its answer or error, the tool calls it made, and its duration."""
    directory = controller.context.directory
    prior = len(session_sources(directory))
    _, events_before = attempted_calls(directory, 0)
    started = time.monotonic()
    try:
        answer, error = controller.run_turn(prompt, lambda event: None), None
    except AgentError as exc:
        answer, error = None, {"code": exc.code, "detail": str(exc)[:2000]}
    attempted, _ = attempted_calls(directory, events_before)
    return {
        "prompt": prompt, "answer": answer, "error": error, "seconds": round(time.monotonic() - started, 1),
        "calls": [call_record(row) for row in session_sources(directory)[prior:]], "attempted_tools": attempted,
    }


def run_script(context: SessionContext, image: str) -> dict:
    """Approve and run the newest script the session proposed, as the review dialog does after the user approves it."""
    proposals = sorted((context.directory / "generated").glob("*.json"), key=lambda path: path.stat().st_mtime) if (context.directory / "generated").is_dir() else []
    if not proposals:
        return {"executed": False, "reason": "no proposal was saved"}
    record = json.loads(proposals[-1].read_text())
    try:
        result = execute_proposal(context, record["proposal_id"], record["sha256"], image)
    except AgentError as exc:
        return {"executed": False, "proposal_id": record["proposal_id"], "reason": f"{exc.code}: {exc}"}
    return {"executed": True, "proposal_id": record["proposal_id"], **{key: result.get(key) for key in ("status", "exit_code", "error", "detail", "stdout_bytes", "output_excerpt")}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--projects-dir", required=True, type=Path)
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--questions", default="", help="comma-separated question IDs, such as 1,2a,23; blank asks all")
    parser.add_argument("--image", required=True, help="the sandbox image ID for question 23's script")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=1800, help="seconds allowed per turn; question 21 gets twice this")
    args = parser.parse_args()
    projects_dir = args.projects_dir.expanduser().resolve()
    runs = json.loads((projects_dir / "eval_runs.json").read_text())
    project = Path(runs["project"])
    quarantine = projects_dir.parent / f"{projects_dir.name}-quarantine"
    adapter = HermesAdapter()
    status = adapter.probe()
    if not status.ready:
        raise SystemExit(status.message)
    models = [name for name in args.models.split(",") if name]
    missing = sorted(set(models) - set(status.models))
    if missing:
        raise SystemExit(f"Not installed: {', '.join(missing)}")
    selected = {item for item in args.questions.split(",") if item}
    report = json.loads(args.report.read_text()) if args.report.exists() else {"projects_dir": str(projects_dir), "runs": runs, "results": []}
    selection = {"": (), "A": (runs["run_a"],), "AB": (runs["run_a"], runs["run_b"]), "C": (runs["run_c"],)}
    for question in questions(runs, projects_dir / "inputs"):
        if selected and question["id"] not in selected:
            continue
        for model in models:
            print(time.strftime("%H:%M:%S"), f"question {question['id']} with {model}", flush=True)
            before = snapshot(project, projects_dir)
            context = SessionContext.create(project, selection[question["runs"]], model, status.endpoint, projects_dir=projects_dir)
            controller = AgentController(context, HermesAdapter(status.endpoint), timeout=args.timeout * (2 if question["id"] == "21" else 1))
            turns = [{"id": question["id"], "pass": question["pass"], **ask(controller, question["prompt"])}]
            if "follow_up" in question:
                execution = run_script(context, args.image)
                follow = question["follow_up"]
                turns.append({"id": follow["id"], "pass": follow["pass"], "script_execution": execution, **ask(controller, follow["prompt"])})
            cleanup = restore(project, projects_dir, before, quarantine / f"{question['id']}-{model.replace(':', '_')}")
            record = {"model": model, "question": question["id"], "runs": list(selection[question["runs"]]), "session": str(context.directory), "turns": turns, "cleanup": cleanup}
            report["results"] = [item for item in report["results"] if (item["model"], item["question"]) != (model, question["id"])] + [record]
            args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False))
            for turn in turns:
                print(f"  {turn['id']}: {turn['seconds']} s, {len(turn['calls'])} calls, {'error ' + turn['error']['code'] if turn['error'] else 'answered'}", flush=True)
            if cleanup:
                print("  cleanup:", "; ".join(cleanup), flush=True)


if __name__ == "__main__":
    main()
