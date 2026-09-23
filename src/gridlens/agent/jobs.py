"""Background jobs the agent starts: GridPACK runs and analysis builds.

A GridPACK run or an analysis build takes minutes, longer than one tool call, and has to outlive the
process that asked for it: the runtime stops the GridLens MCP server at the end of every turn. So a tool
writes a job record and starts a separate GridLens process, in its own session, that does the work and
records its progress. The agent reads that record in later calls, or in later turns.

Each job has a folder, `<project>/agent/jobs/<job_id>/`, holding:

- `job.json`, what was asked: the kind, the project and run folders, the request, and the worker's pid;
- `status.json`, the state (queued, running, completed, failed, or cancelled), a message, and, once the
  job ends, its result;
- `output.log`, everything the worker printed, including a traceback if it failed.

The worker is `gridlens --agent-job <job folder>`, which runs `run_job`.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import traceback
from uuid import uuid4

from gridlens.agent.policy import AgentError
from gridlens.agent.process import gridlens_command
from gridlens.agent.session import PROJECT_FILE, read_json, scoped_path, timestamp, write_json


JOBS_FOLDER = Path("agent/jobs")
JOB_KINDS = ("gridpack_run", "analysis")
FINAL_STATES = ("completed", "failed", "cancelled")
JOB_ID_PATTERN = re.compile(r"\d{8}T\d{6}Z_[a-f0-9]{8}")
LOG_TAIL_LINES = 20
POLL_SECONDS = 2.0
CANCEL_WAIT_SECONDS = 15.0


def _write_status(folder: Path, state: str, message: str, **details: object) -> None:
    """Replace a job's status.json in one step, so a reader never sees a half-written file.

    The last progress snapshot is kept when an update does not bring a new one, so a finished job
    still shows how far it got.
    """
    path = folder / "status.json"
    if "progress" not in details and path.is_file():
        details["progress"] = json.loads(path.read_text(encoding="utf-8")).get("progress")
    value = {"state": state, "message": message[:4000], "updated_at": timestamp(), **details}
    temporary = folder / "status.json.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(temporary, folder / "status.json")


def job_folder(project_root: Path, job_id: str) -> Path:
    """Return the folder of one job of a project, refusing an ID that is not a job ID."""
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
        raise AgentError("INVALID_JOB_ID", "Use a job ID returned by start_run, run_analysis, or list_jobs.")
    folder = scoped_path(project_root, JOBS_FOLDER / job_id, directory=True)
    if not (folder / "job.json").is_file():
        raise AgentError("JOB_NOT_FOUND", "This project has no such job. Use list_jobs to see its jobs.")
    return folder


def _log_tail(path: Path, lines: int = LOG_TAIL_LINES) -> list[str]:
    """Return the last lines of a log file, or an empty list when it does not exist."""
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 64 * 1024))
        return handle.read().decode("utf-8", errors="replace").splitlines()[-lines:]


def _alive(pid: object) -> bool:
    """Return whether the worker with this pid is still running.

    The process that started a worker is its parent until it exits, so a finished worker lingers as a
    zombie there; reaping it first keeps a stopped worker from looking alive.
    """
    try:
        finished, _ = os.waitpid(int(pid), os.WNOHANG)
        if finished:
            return False
    except ChildProcessError:
        pass
    except (TypeError, ValueError):
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_job(project_root: Path, job_id: str) -> dict:
    """Return a job's request, state, result, and the last lines of its output.

    A job still marked queued or running whose worker no longer exists is reported as failed, because
    the worker records every outcome it reaches, so only a crash leaves it unrecorded.
    """
    folder = job_folder(project_root, job_id)
    record = read_json(folder / "job.json")
    status = read_json(folder / "status.json") if (folder / "status.json").is_file() else {"state": "queued", "message": ""}
    if status.get("state") not in FINAL_STATES and not _alive(record.get("pid")):
        status = {**status, "state": "failed", "message": "The job's worker process ended without recording a result. See output_tail."}
    return {**record, **status, "output_log": str(folder / "output.log"), "output_tail": _log_tail(folder / "output.log")}


def list_jobs(project_root: Path) -> list[dict]:
    """Return every job of a project, newest first."""
    root = scoped_path(project_root, JOBS_FOLDER, directory=True)
    if not root.is_dir():
        return []
    names = sorted((path.name for path in root.iterdir() if JOB_ID_PATTERN.fullmatch(path.name)), reverse=True)
    return [read_job(project_root, name) for name in names]


def start_job(project_root: Path, kind: str, run_dir: Path, request: dict) -> dict:
    """Record a job and start its worker as a separate process in its own session; return the job."""
    if kind not in JOB_KINDS:
        raise AgentError("INVALID_JOB_KIND", "Jobs run GridPACK or build an analysis.")
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:8]
    folder = scoped_path(project_root, JOBS_FOLDER / job_id, directory=True)
    folder.mkdir(parents=True, mode=0o700)
    record = {"job_id": job_id, "kind": kind, "project_root": str(project_root), "run_id": run_dir.name, "run_dir": str(run_dir), "request": request, "created_at": timestamp()}
    write_json(folder / "job.json", record, exclusive=True)
    _write_status(folder, "queued", "Waiting for the worker to start.")
    with (folder / "output.log").open("ab") as log:
        worker = subprocess.Popen(gridlens_command("--agent-job", str(folder)), cwd=folder, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    write_json(folder / "job.json", {**record, "pid": worker.pid})
    return read_job(project_root, job_id)


def wait_for_job(project_root: Path, job_id: str, seconds: float) -> dict:
    """Return a job once it ends, or its current state after waiting at most seconds."""
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        job = read_job(project_root, job_id)
        if job["state"] in FINAL_STATES or time.monotonic() >= deadline:
            return job
        time.sleep(min(POLL_SECONDS, max(0.0, deadline - time.monotonic())))


def cancel_job(project_root: Path, job_id: str) -> dict:
    """Stop a job: signal its worker's process group, and stop the GridPACK container of a run job.

    The worker records the cancellation itself when it can. One that exits without doing so, within
    CANCEL_WAIT_SECONDS, is recorded as cancelled here.
    """
    from gridlens.runner.gridpack_runner import effective_gridpack_container_name, terminate_gridpack_run

    folder = job_folder(project_root, job_id)
    job = read_json(folder / "job.json")
    if read_json(folder / "status.json").get("state") in FINAL_STATES:
        return read_job(project_root, job_id)
    try:
        os.killpg(int(job["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, KeyError, TypeError, ValueError):
        pass
    if job["kind"] == "gridpack_run":
        extra = (job.get("request") or {}).get("form", {}).get("extra_docker_args", "")
        terminate_gridpack_run(effective_gridpack_container_name(job["run_dir"], extra))
    deadline = time.monotonic() + CANCEL_WAIT_SECONDS
    while _alive(job.get("pid")) and time.monotonic() < deadline:
        time.sleep(0.1)
    if not _alive(job.get("pid")) and read_json(folder / "status.json").get("state") not in FINAL_STATES:
        _write_status(folder, "cancelled", "The job was stopped before it finished.")
    return read_job(project_root, job_id)


def _run_gridpack(job: dict, folder: Path) -> dict:
    """Run GridPACK for a job and return its outcome, recording progress as the run streams output."""
    from gridlens.core.project import ProjectData
    from gridlens.gui.run_view_models import RunFormValues, build_gridpack_run_request
    from gridlens.runner.gridpack_runner import run_gridpack_case
    from gridlens.runner.run_progress import GridpackProgressParser

    project_data = ProjectData.from_dict(read_json(Path(job["project_root"]) / PROJECT_FILE))
    request = build_gridpack_run_request(project_data, Path(job["run_dir"]), RunFormValues(**job["request"]["form"]))
    request.notes = job["request"].get("notes", "")
    parser = GridpackProgressParser()

    def on_line(line: str) -> None:
        """Record each progress update the run's output reveals."""
        update = parser.feed(line)
        if update is not None:
            _write_status(folder, "running", update.message, progress=asdict(update))

    result = run_gridpack_case(request, log_callback=on_line)
    return {"ok": result.return_code == 0, "message": f"GridPACK exited with code {result.return_code}.", "return_code": result.return_code, "run_log": str(result.log_file)}


def analysis_summary(tables: dict, kind: str) -> dict:
    """Summarize one analysis for a job result: facility count, group counts, and the highest loading."""
    from gridlens.analysis.loading import max_line_utilization_rows, summarize_control_area_utilization, summarize_voltage_group_utilization
    from gridlens.analysis.utilization import DEFAULT_UTILIZATION_BRANCH_OPTIONS, TRANSFORMER_UTILIZATION_BRANCH_OPTIONS

    options = TRANSFORMER_UTILIZATION_BRANCH_OPTIONS if kind == "transformer" else DEFAULT_UTILIZATION_BRANCH_OPTIONS
    rows = max_line_utilization_rows(tables, options)
    worst = max(rows, key=lambda row: float(row["max_utilization_pct"]), default=None)
    return {
        "facility_count": len(rows),
        "control_area_groups": len(summarize_control_area_utilization(rows)),
        "voltage_groups": len(summarize_voltage_group_utilization(rows)),
        "highest_max_utilization_pct": float(worst["max_utilization_pct"]) if worst else None,
        "highest_loaded_facility": worst["line_label"] if worst else None,
    }


def _run_analysis(job: dict, folder: Path, cancelled: threading.Event) -> dict:
    """Build a run's analysis cache, and optionally its event index, then summarize the requested analyses."""
    from gridlens.analysis.csv_flat import CSV_FLAT_ALLOW_CPU_DASK_ENV, cpu_dask_fallback_warning
    from gridlens.analysis.service import AnalysisService
    from gridlens.analysis.utilization import DEFAULT_UTILIZATION_BRANCH_OPTIONS

    run_dir = Path(job["run_dir"])
    request = job["request"]
    # Nobody is at the screen to accept the GUI's CPU fallback prompt, so the job accepts it and says so.
    warning = cpu_dask_fallback_warning(run_dir)
    os.environ[CSV_FLAT_ALLOW_CPU_DASK_ENV] = "1"

    def progress(update) -> None:
        """Record each phase of the build."""
        _write_status(folder, "running", update.detail or update.phase, progress={"phase": update.phase, "fraction": update.fraction})

    result = AnalysisService.build(run_dir, DEFAULT_UTILIZATION_BRANCH_OPTIONS, progress, cancelled, indexed=bool(request.get("include_index")), rebuild=bool(request.get("rebuild")))
    summaries = {kind: analysis_summary(result.dataset.tables, kind) for kind in request.get("kinds", ["branch"])}
    return {"ok": True, "message": "The analysis cache is ready; query it with the analysis tools.", "summaries": summaries, "cpu_fallback_warning": warning}


def run_job(folder: Path) -> int:
    """Run the job recorded in folder to its end, recording its outcome in status.json; return an exit code."""
    job = read_json(folder / "job.json")
    cancelled = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
    _write_status(folder, "running", "Started.")
    try:
        if job["kind"] == "gridpack_run":
            outcome = _run_gridpack(job, folder)
        elif job["kind"] == "analysis":
            outcome = _run_analysis(job, folder, cancelled)
        else:
            raise ValueError(f"Unknown job kind {job['kind']!r}.")
    except Exception as exc:
        traceback.print_exc()
        state = "cancelled" if cancelled.is_set() else "failed"
        _write_status(folder, state, f"{type(exc).__name__}: {exc}")
        return 1
    state = "cancelled" if cancelled.is_set() else "completed" if outcome.pop("ok") else "failed"
    _write_status(folder, state, outcome.pop("message"), result=outcome)
    return 0 if state == "completed" else 1


def main(argv: list[str]) -> int:
    """Entry point for `gridlens --agent-job <job folder>`."""
    if len(argv) != 1:
        print("usage: gridlens --agent-job JOB_FOLDER", flush=True)
        return 2
    folder = Path(argv[0]).resolve()
    if not (folder / "job.json").is_file():
        print(f"No job record in {folder}.", flush=True)
        return 2
    return run_job(folder)
