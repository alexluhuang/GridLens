"""Background jobs the agent starts: GridPACK runs and analysis builds.

A GridPACK run or an analysis build takes minutes, longer than one tool call, and has to outlive the
process that asked for it: the runtime stops the GridLens MCP server at the end of every turn. So a tool
writes a job record and starts a separate GridLens process, in its own session, that does the work and
records its progress. The agent reads that record in later calls, or in later turns.

Each job has a folder, `<project>/agent/jobs/<job_id>/`, holding two files:

- `job.json`, the whole record: what was asked (the kind, the project and run folders, the request, the
  conversation that started it) and where the job stands now (queued, running, completed, failed, or
  cancelled), with a message, the latest progress, the worker's pid, and, once the job ends, its result;
- `job.log`, a readable, timestamped history of the job: when it started, its progress, how it ended, and
  anything the worker printed, including a traceback if it failed.

Jobs recorded by earlier versions of GridLens kept the state in a separate `status.json` and the worker's
output in `output.log`; they are still read.

A GridPACK run job that completes goes on to prepare the run's branch and transformer analysis, as a
run from the Run tab does, so its results can be queried as soon as the job ends.

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
JOB_FILE = "job.json"
LOG_FILE = "job.log"
# Jobs written before the record and the state shared one file.
LEGACY_STATUS_FILE = "status.json"
LEGACY_LOG_FILE = "output.log"
LOG_TAIL_LINES = 20
POLL_SECONDS = 2.0
CANCEL_WAIT_SECONDS = 15.0
# The worker waits this long for start_job to record its pid before it writes the record itself.
PID_WAIT_SECONDS = 10.0
# Streaming progress, such as one line per contingency, is logged at most this often.
PROGRESS_LOG_SECONDS = 5.0
STATE_FIELDS = ("state", "message", "updated_at", "progress", "result")


def _log(folder: Path, text: str) -> None:
    """Append one timestamped line, or a timestamped block, to the job's log."""
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = str(text).rstrip("\n").splitlines() or [""]
    with (folder / LOG_FILE).open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}  {lines[0]}\n" + "".join(f"    {line}\n" for line in lines[1:]))


def _replace_record(folder: Path, record: dict) -> None:
    """Replace job.json in one step, so a reader never sees a half-written file."""
    temporary = folder / f"{JOB_FILE}.{os.getpid()}.tmp"
    temporary.unlink(missing_ok=True)
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
    os.replace(temporary, folder / JOB_FILE)


def _write_status(folder: Path, state: str, message: str, **details: object) -> None:
    """Record a job's new state in job.json, keeping the request and the last progress snapshot.

    The last progress snapshot is kept when an update does not bring a new one, so a finished job
    still shows how far it got.
    """
    record = read_json(folder / JOB_FILE)
    if "progress" not in details:
        details["progress"] = record.get("progress")
    record.update({"state": state, "message": message[:4000], "updated_at": timestamp(), **details})
    _replace_record(folder, record)


def _wait_for_pid(folder: Path) -> None:
    """Wait until start_job has recorded this worker's pid, so the two never write job.json at once.

    A worker started some other way records its own pid once the wait runs out.
    """
    deadline = time.monotonic() + PID_WAIT_SECONDS
    while time.monotonic() < deadline:
        if read_json(folder / JOB_FILE).get("pid") is not None:
            return
        time.sleep(0.05)
    record = read_json(folder / JOB_FILE)
    if record.get("pid") is None:
        _replace_record(folder, {**record, "pid": os.getpid()})


def job_folder(project_root: Path, job_id: str) -> Path:
    """Return the folder of one job of a project, refusing an ID that is not a job ID."""
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
        raise AgentError("INVALID_JOB_ID", "Use a job ID returned by start_run, run_analysis, or get_status.")
    folder = scoped_path(project_root, JOBS_FOLDER / job_id, directory=True)
    if not (folder / JOB_FILE).is_file():
        raise AgentError("JOB_NOT_FOUND", "This project has no such job. Call get_status without a job_id to list its jobs.")
    return folder


def log_tail(path: Path, lines: int = LOG_TAIL_LINES) -> list[str]:
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


def _state(folder: Path, record: dict) -> dict:
    """Return the state fields of a job, from job.json or, for a legacy job, from its status.json."""
    legacy = folder / LEGACY_STATUS_FILE
    if "state" not in record and legacy.is_file():
        return read_json(legacy)
    status = {key: record[key] for key in STATE_FIELDS if key in record}
    return status if "state" in status else {"state": "queued", "message": ""}


def read_job(project_root: Path, job_id: str) -> dict:
    """Return a job's request, state, result, and the last lines of its log.

    A job still marked queued or running whose worker no longer exists is reported as failed, because
    the worker records every outcome it reaches, so only a crash leaves it unrecorded. A queued job whose
    pid is not recorded yet is being started, and is reported as queued.
    """
    folder = job_folder(project_root, job_id)
    record = read_json(folder / JOB_FILE)
    status = _state(folder, record)
    starting = status.get("state") == "queued" and record.get("pid") is None and not (folder / LEGACY_STATUS_FILE).is_file()
    if status.get("state") not in FINAL_STATES and not starting and not _alive(record.get("pid")):
        status = {**status, "state": "failed", "message": "The job's worker process ended without recording a result. See log_tail."}
    log = folder / (LOG_FILE if (folder / LOG_FILE).is_file() or not (folder / LEGACY_LOG_FILE).is_file() else LEGACY_LOG_FILE)
    request = {key: value for key, value in record.items() if key not in STATE_FIELDS}
    return {**request, **status, "log": str(log), "log_tail": log_tail(log)}


def list_jobs(project_root: Path) -> list[dict]:
    """Return every job of a project, newest first."""
    root = scoped_path(project_root, JOBS_FOLDER, directory=True)
    if not root.is_dir():
        return []
    names = sorted((path.name for path in root.iterdir() if JOB_ID_PATTERN.fullmatch(path.name) and (path / JOB_FILE).is_file()), reverse=True)
    return [read_job(project_root, name) for name in names]


def start_job(project_root: Path, kind: str, run_dir: Path, request: dict, *, conversation: Path | None = None) -> dict:
    """Record a job and start its worker as a separate process in its own session; return the job.

    conversation is the session folder of the conversation that asked for the job, recorded so a reader
    of either can find the other.
    """
    if kind not in JOB_KINDS:
        raise AgentError("INVALID_JOB_KIND", "Jobs run GridPACK or build an analysis.")
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:8]
    folder = scoped_path(project_root, JOBS_FOLDER / job_id, directory=True)
    folder.mkdir(parents=True, mode=0o700)
    record = {
        "job_id": job_id, "kind": kind, "project_root": str(project_root), "run_id": run_dir.name, "run_dir": str(run_dir),
        "request": request, "conversation": str(conversation) if conversation else None, "created_at": timestamp(),
        "pid": None, "state": "queued", "message": "Waiting for the worker to start.", "updated_at": timestamp(),
    }
    _replace_record(folder, record)
    _log(folder, f"Queued {kind} job for run {run_dir.name}." + (f" Started by the conversation in {conversation}." if conversation else ""))
    with (folder / LOG_FILE).open("ab") as log:
        worker = subprocess.Popen(gridlens_command("--agent-job", str(folder)), cwd=folder, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    # The worker waits for this pid before it writes job.json, so this is the starter's only write after the spawn.
    _replace_record(folder, {**record, "pid": worker.pid})
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
    CANCEL_WAIT_SECONDS, is recorded as cancelled here, once it is gone.
    """
    from gridlens.runner.gridpack_runner import effective_gridpack_container_name, terminate_gridpack_run

    folder = job_folder(project_root, job_id)
    job = read_json(folder / JOB_FILE)
    if _state(folder, job).get("state") in FINAL_STATES:
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
    if not _alive(job.get("pid")) and _state(folder, read_json(folder / JOB_FILE)).get("state") not in FINAL_STATES:
        if (folder / LEGACY_STATUS_FILE).is_file() and "state" not in job:
            write_json(folder / LEGACY_STATUS_FILE, {"state": "cancelled", "message": "The job was stopped before it finished.", "updated_at": timestamp()})
        else:
            _write_status(folder, "cancelled", "The job was stopped before it finished.")
            _log(folder, "Cancelled: the job was stopped before it finished.")
    return read_job(project_root, job_id)


class _ProgressLog:
    """Log progress updates without flooding job.log: a changed phase at once, streaming updates every few seconds."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.phase = None
        self.last = 0.0
        self.pending = ""

    def update(self, phase: object, message: str) -> None:
        """Log message now if the phase changed or enough time has passed; otherwise keep it for flush."""
        now = time.monotonic()
        if phase != self.phase or now - self.last >= PROGRESS_LOG_SECONDS:
            _log(self.folder, message)
            self.phase, self.last, self.pending = phase, now, ""
        else:
            self.pending = message

    def flush(self) -> None:
        """Log the last update that was held back, so the log shows how far the job got."""
        if self.pending:
            _log(self.folder, self.pending)
            self.pending = ""


def _run_gridpack(job: dict, folder: Path) -> dict:
    """Run GridPACK for a job and return its outcome, recording progress as the run streams output."""
    from gridlens.core.project import ProjectData
    from gridlens.gui.run_view_models import RunFormValues, build_gridpack_run_request
    from gridlens.runner.gridpack_runner import run_gridpack_case
    from gridlens.runner.run_progress import GridpackProgressParser

    project_data = ProjectData.from_dict(read_json(Path(job["project_root"]) / PROJECT_FILE))
    request = build_gridpack_run_request(project_data, Path(job["run_dir"]), RunFormValues(**job["request"]["form"]))
    request.notes = job["request"].get("notes", "")
    # A sensitivity run's work folder already holds the edited case and a copy of the XML that names it.
    if job["request"].get("xml_file"):
        request.xml_filename = job["request"]["xml_file"]
    parser = GridpackProgressParser()
    progress_log = _ProgressLog(folder)
    _log(folder, f"Running GridPACK with {request.mpi_processes} MPI processes in {request.image}. The full GridPACK output is in {Path(job['run_dir']) / 'logs/run.log'}.")

    def on_line(line: str) -> None:
        """Record each progress update the run's output reveals."""
        update = parser.feed(line)
        if update is not None:
            _write_status(folder, "running", update.message, progress=asdict(update))
            progress_log.update(update.phase, update.message)

    try:
        result = run_gridpack_case(request, log_callback=on_line)
    finally:
        progress_log.flush()
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

    if warning:
        _log(folder, warning)
    progress_log = _ProgressLog(folder)

    def progress(update) -> None:
        """Record each phase of the build."""
        _write_status(folder, "running", update.detail or update.phase, progress={"phase": update.phase, "fraction": update.fraction})
        progress_log.update(update.phase, update.detail or update.phase)

    try:
        result = AnalysisService.build(run_dir, DEFAULT_UTILIZATION_BRANCH_OPTIONS, progress, cancelled, indexed=bool(request.get("include_index")), rebuild=bool(request.get("rebuild")))
    finally:
        progress_log.flush()
    summaries = {kind: analysis_summary(result.dataset.tables, kind) for kind in request.get("kinds", ["branch"])}
    return {"ok": True, "message": "The analysis cache is ready; query it with the analysis tools.", "summaries": summaries, "cpu_fallback_warning": warning}


def _analyze_finished_run(job: dict, folder: Path, outcome: dict, cancelled: threading.Event) -> dict:
    """Prepare the branch and transformer analysis of a run that completed, as the Run tab does.

    The run has succeeded whatever happens here, so a failed build is reported in the outcome rather than
    failing the job; run_analysis can retry it.
    """
    _log(folder, "GridPACK finished. Preparing the branch and transformer analysis.")
    try:
        analysis = _run_analysis({**job, "request": {"kinds": ["branch", "transformer"]}}, folder, cancelled)
    except Exception as exc:
        if cancelled.is_set():
            return {**outcome, "message": outcome["message"] + " Preparing its analysis was stopped."}
        _log(folder, f"Preparing the analysis failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        detail = (str(exc).strip().splitlines() or [type(exc).__name__])[-1][:500]
        return {**outcome, "message": outcome["message"] + " Preparing its analysis failed; run_analysis can retry it.", "analysis_error": detail}
    return {
        **outcome, "message": outcome["message"] + " The branch and transformer analysis is ready.",
        "summaries": analysis["summaries"], "cpu_fallback_warning": analysis["cpu_fallback_warning"],
    }


def _outcome_lines(outcome: dict) -> str:
    """Describe a job's result for job.log, one line per item."""
    lines = []
    for kind, summary in (outcome.get("summaries") or {}).items():
        highest = summary.get("highest_max_utilization_pct")
        lines.append(
            f"{kind}: {summary.get('facility_count', 0):,} facilities"
            + (f"; highest loading {highest:.1f}% on {summary.get('highest_loaded_facility')}" if highest is not None else "")
        )
    lines.extend(f"{key}: {value}" for key, value in outcome.items() if key != "summaries" and value not in ("", None))
    return "\n".join(lines)


def run_job(folder: Path) -> int:
    """Run the job recorded in folder to its end, recording its outcome in job.json and job.log; return an exit code."""
    _wait_for_pid(folder)
    job = read_json(folder / JOB_FILE)
    cancelled = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
    _write_status(folder, "running", "Started.")
    _log(folder, f"Started the {job['kind']} job for run {job.get('run_id')} (worker pid {os.getpid()}).")
    final = {}
    try:
        if job["kind"] == "gridpack_run":
            outcome = _run_gridpack(job, folder)
            if outcome["ok"] and not cancelled.is_set():
                # The record ends with how far GridPACK got, not with the analysis build's last phase.
                final["progress"] = read_json(folder / JOB_FILE).get("progress")
                outcome = _analyze_finished_run(job, folder, outcome, cancelled)
        elif job["kind"] == "analysis":
            outcome = _run_analysis(job, folder, cancelled)
        else:
            raise ValueError(f"Unknown job kind {job['kind']!r}.")
    except Exception as exc:
        state = "cancelled" if cancelled.is_set() else "failed"
        _write_status(folder, state, f"{type(exc).__name__}: {exc}")
        _log(folder, f"{state.capitalize()}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 1
    state = "cancelled" if cancelled.is_set() else "completed" if outcome.pop("ok") else "failed"
    message = outcome.pop("message")
    _write_status(folder, state, message, result=outcome, **final)
    details = _outcome_lines(outcome)
    _log(folder, f"{state.capitalize()}: {message}" + (f"\n{details}" if details else ""))
    return 0 if state == "completed" else 1


def main(argv: list[str]) -> int:
    """Entry point for `gridlens --agent-job <job folder>`."""
    if len(argv) != 1:
        print("usage: gridlens --agent-job JOB_FOLDER", flush=True)
        return 2
    folder = Path(argv[0]).resolve()
    if not (folder / JOB_FILE).is_file():
        print(f"No job record in {folder}.", flush=True)
        return 2
    return run_job(folder)
