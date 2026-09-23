"""Prepare a projects folder for the planning-question evaluation in `evaluate_agent_questions.py`.

It copies a sample project without its agent sessions and then gives the copy four runs:

- A, the sample run, with its analysis rebuilt and a drill-down index;
- B, a GridPACK run of a case that moves 3% of Coast load's worth of MW from North Central to Coast,
  with its analysis and index, for the comparison questions;
- C, run A's results linked under a new run with no analysis, for the question asked before one is built;
- D, a run that failed partway, with a partial log and no results, for the question about incomplete runs.

It also writes the inputs the setup questions name: the sample RAW case and a two-outage contingency list.
The net load does not change because the sample case's slack generator is rated 275 MW and carries about
150 MW: raising Coast load 5% alone overloaded it in every contingency. Each step is skipped when its
output exists, so rerunning the script only adds what is missing. eval_runs.json records the run IDs.

    python scripts/prepare_agent_evaluation.py --source ~/GridLensProjects/GridPACK_Test_Project --projects-dir ~/GridLensProjects-eval
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import time

from gridlens.agent.session import SessionContext
from gridlens.agent.tools import ToolService
from gridlens.analysis.event_index import INDEX_VERSION
from gridlens.analysis.raw_sections import read_raw_sections

RAW_CASE = "Texas7k_20210804.raw"
IMAGE = "pnnl/gridpack:ca-scalability-v2"
COAST, NORTH_CENTRAL = 7, 5
CONTINGENCIES = (("CTG_BRYAN", "230273 230288"), ("CTG_COAST", "110001 110041"))


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def wait(tools: ToolService, job_id: str) -> dict:
    """Wait for a background job to end and return it."""
    while True:
        job = tools.get_status(job_id=job_id, wait_seconds=1500)["data"]["rows"][0]
        log(f"job {job_id}: {job['state']} {job.get('message', '')[:120]}")
        if job["state"] in ("completed", "failed", "cancelled"):
            return job


def indexed(run: Path) -> bool:
    """Return whether a run has a drill-down index of the current version."""
    manifest = run / "reports/event_index/manifest.json"
    return manifest.is_file() and json.loads(manifest.read_text()).get("version") == INDEX_VERSION


def area_loads(case: Path) -> dict[int, float]:
    """Return the in-service real load of each area of a RAW case, in MW."""
    _, sections = read_raw_sections(case)
    totals: dict[int, float] = {}
    for row in next(section for section in sections if section.name == "LOAD").rows:
        if str(row["STATUS"]).strip() == "1":
            totals[int(row["AREA"])] = totals.get(int(row["AREA"]), 0.0) + float(row["PL"])
    return totals


def scaled_case(source: Path, target: Path, factors: dict[int, float]) -> dict[int, float]:
    """Write a copy of a RAW case with every load of each area in factors scaled by its factor; return the MW added per area."""
    lines = source.read_text(encoding="latin-1").splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines) if "BEGIN LOAD DATA" in line.upper())
    added = {area: 0.0 for area in factors}
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("0 /") or lines[index].strip() == "0":
            break
        fields = lines[index].rstrip("\n").split(",")
        area = int(fields[3]) if len(fields) > 6 else None
        if area in factors:
            pl, ql = float(fields[5]), float(fields[6])
            added[area] += pl * (factors[area] - 1)
            fields[5], fields[6] = f"{pl * factors[area]:10.3f}", f"{ql * factors[area]:10.3f}"
            lines[index] = ",".join(fields) + "\n"
    target.write_text("".join(lines), encoding="latin-1")
    return added


def contingency_list() -> str:
    """Return a GridPACK contingency list of two line outages."""
    entries = "".join(
        f"      <Contingency>\n        <contingencyType>Line</contingencyType>\n        <contingencyName>{name}</contingencyName>\n"
        f"        <contingencyLineBuses>{buses}</contingencyLineBuses>\n        <contingencyLineNames>1</contingencyLineNames>\n      </Contingency>\n"
        for name, buses in CONTINGENCIES
    )
    return f'<?xml version="1.0" encoding="utf-8"?>\n<ContingencyList>\n  <Contingency_analysis>\n    <Contingencies>\n{entries}    </Contingencies>\n  </Contingency_analysis>\n</ContingencyList>\n'


def linked_run(project: Path, source: str, run_id: str, status: dict, *, keep=lambda path: True, log_lines: int = 0) -> None:
    """Make a run folder whose files are hard links to another run's, with its own manifest and status.

    log_lines keeps only the first lines of the run's two logs, as a run stopped partway leaves them.
    """
    folder = project / "runs" / run_id
    for name in ("work", "logs"):
        (folder / name).mkdir(parents=True)
        for path in (project / "runs" / source / name).iterdir():
            if path.suffix == ".log" and log_lines:
                with path.open(encoding="utf-8", errors="replace") as handle:
                    (folder / name / path.name).write_text("".join(line for _, line in zip(range(log_lines), handle)))
            elif keep(path):
                os.link(path, folder / name / path.name)
    manifest = json.loads((project / "runs" / source / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps({**manifest, "run_id": run_id, "container_name": f"gridlens-{run_id}"}, indent=2))
    (folder / "status.json").write_text(json.dumps(status))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", required=True, type=Path, help="the sample project to copy")
    parser.add_argument("--run", default="2026-07-28_14-46-26", help="the sample project's run to use as run A")
    parser.add_argument("--projects-dir", required=True, type=Path, help="a new folder for the copy and the inputs")
    args = parser.parse_args()
    root = args.projects_dir.expanduser().resolve()
    project = root / args.source.name
    inputs = root / "inputs"
    record_path = root / "eval_runs.json"
    record = json.loads(record_path.read_text()) if record_path.is_file() else {}
    inputs.mkdir(parents=True, exist_ok=True)
    if not project.exists():
        log("copying the sample project without its agent sessions")
        shutil.copytree(args.source.expanduser(), project, ignore=shutil.ignore_patterns("agent"), copy_function=shutil.copy2)
        data = json.loads((project / "project.json").read_text())
        data["root_dir"] = str(project)
        for item in data["input_files"]:
            item["stored_path"] = str(project / "original_inputs" / item["file_name"])
        (project / "project.json").write_text(json.dumps(data, indent=2))
    service: list[ToolService] = []

    def tools() -> ToolService:
        """Return the setup session's tools, starting the session the first time a step needs them."""
        if not service:
            service.append(ToolService(SessionContext.create(project, (args.run,), "setup", "http://127.0.0.1:11434", projects_dir=root)))
        return service[0]

    run_a = project / "runs" / args.run
    if not indexed(run_a):
        log("rebuilding run A's analysis with the contingency summary and the drill-down index")
        wait(tools(), tools().run_analysis(args.run, include_index=True, rebuild=True)["data"]["job_id"])

    case = inputs / "Texas7k_coast_shift_3pct.raw"
    if not (record.get("run_b") and (project / "runs" / record["run_b"]).is_dir()):
        loads = area_loads(project / "original_inputs" / RAW_CASE)
        shift = loads[COAST] * 0.03
        added = scaled_case(project / "original_inputs" / RAW_CASE, case, {COAST: 1.03, NORTH_CENTRAL: 1 - shift / loads[NORTH_CENTRAL]})
        log(f"Coast load {added[COAST]:+.1f} MW, North Central load {added[NORTH_CENTRAL]:+.1f} MW")
        original_xml = (project / "original_inputs/input.xml").read_text()
        assert tools().add_project_inputs([str(case)])["error"] is None
        assert tools().configure_run({"network_file_name": case.name})["error"] is None
        started = tools().start_run(image=IMAGE, mpi_processes=20, notes="Evaluation run B: 3% of Coast load moved from North Central to Coast")
        assert started["error"] is None, started
        record.update(run_b=started["data"]["run_id"], coast_load_added_mw=round(added[COAST], 1), north_central_load_added_mw=round(added[NORTH_CENTRAL], 1))
        assert wait(tools(), started["data"]["job_id"])["state"] == "completed"
        (project / "original_inputs/input.xml").write_text(original_xml)
        log("restored the project XML to the original case and settings")
    if not indexed(project / "runs" / record["run_b"]):
        log(f"building run B ({record['run_b']}) analysis and index")
        wait(tools(), tools().run_analysis(record["run_b"], include_index=True)["data"]["job_id"])

    record.update(project=str(project), run_a=args.run, run_c="2026-09-24_00-00-00", run_d="2026-09-24_01-00-00")
    if not (project / "runs" / record["run_c"]).exists():
        linked_run(project, args.run, record["run_c"], {"status": "completed", "return_code": 0})
        log(f"run C ({record['run_c']}) has run A's results and no analysis")
    if not (project / "runs" / record["run_d"]).exists():
        # A run killed partway: its inputs and the first part of its log, and no results.
        linked_run(project, args.run, record["run_d"], {"status": "failed", "return_code": 137}, keep=lambda path: path.suffix != ".csv", log_lines=20000)
        log(f"run D ({record['run_d']}) failed partway and has no results")
    for name, text in (("contingencies.xml", contingency_list()),):
        if not (inputs / name).exists():
            (inputs / name).write_text(text)
    if not (inputs / RAW_CASE).exists():
        shutil.copy2(project / "original_inputs" / RAW_CASE, inputs / RAW_CASE)
    record_path.write_text(json.dumps(record, indent=2))
    log(f"done: {record_path}")


if __name__ == "__main__":
    main()
