from __future__ import annotations

import fcntl
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from gridlens.analysis.service import AnalysisService, _terminate_group
from gridlens.analysis.utilization import UtilizationBranchOptions
from gridlens.gui import agent_jobs


def test_shared_service_builds_in_spawned_worker(agent_project):
    updates = []
    result = AnalysisService.build(agent_project / "runs/run_a", UtilizationBranchOptions(), updates.append)
    assert result.max_line_rows
    assert max(row["max_utilization_pct"] for row in result.max_line_rows) == 120
    assert updates


def test_waiting_shared_job_can_be_cancelled(agent_project):
    cancelled = threading.Event()
    lock_path = Path("/tmp") / f"gridlens-analysis-{os.getuid()}.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        timer = threading.Timer(0.2, cancelled.set)
        timer.start()
        try:
            with pytest.raises(RuntimeError, match="cancelled"):
                AnalysisService.build(agent_project / "runs/run_a", UtilizationBranchOptions(), cancelled=cancelled)
        finally:
            timer.cancel()


def _sleeper_with_grandchild(pid_path: str) -> None:
    os.setsid()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    Path(pid_path).write_text(f"{os.getpid()} {child.pid}\n")
    time.sleep(120)


def _wait_for_pids(pid_path: Path) -> list[int]:
    for _ in range(1500):
        try:
            fields = pid_path.read_text().split()
        except FileNotFoundError:
            fields = []
        if len(fields) == 2:
            return [int(field) for field in fields]
        time.sleep(0.02)
    pytest.fail("worker never reported its own pid and its grandchild pid")


def _process_gone(pid: int) -> bool:
    for _ in range(250):
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError, IndexError):
            return True
        if state == "Z":  # orphan already dead, waiting for init to reap it
            return True
        time.sleep(0.02)
    return False


def _own_child_pids() -> set[int]:
    pids = set()
    for children in Path("/proc/self/task").glob("*/children"):
        try:
            pids.update(int(pid) for pid in children.read_text().split())
        except FileNotFoundError:
            continue
    return pids


def test_terminate_group_kills_worker_and_grandchild(tmp_path):
    pid_path = tmp_path / "pids.txt"
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_sleeper_with_grandchild, args=(str(pid_path),))
    process.start()
    try:
        worker_pid, grandchild_pid = _wait_for_pids(pid_path)
    finally:
        _terminate_group(process)
    assert process.exitcode is not None
    assert _process_gone(worker_pid), "cancelled analysis worker survived the group kill"
    assert _process_gone(grandchild_pid), "analysis worker grandchild survived the group kill"


def test_in_flight_build_is_cancelled_and_worker_is_reaped(agent_project):
    cancelled = threading.Event()
    updates = []

    def cancel_once_building(update):
        updates.append(update)
        if "Waiting" not in update.detail:  # the lock-wait notice proves nothing; worker progress means context.Process started
            cancelled.set()

    before = _own_child_pids()
    with pytest.raises(RuntimeError, match="cancelled"):
        AnalysisService.build(agent_project / "runs/run_a", UtilizationBranchOptions(), progress=cancel_once_building, cancelled=cancelled)
    assert cancelled.is_set()
    assert not _own_child_pids() - before


def _worker_with_failing_build(monkeypatch, error, tmp_path):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(agent_jobs, "AnalysisService", SimpleNamespace(build=fail))
    worker = agent_jobs.AgentAnalysisWorker([tmp_path / "run_a"], False, None)
    outcomes, progress = [], []
    worker.outcome.connect(outcomes.append)
    worker.progress.connect(progress.append)
    return worker, outcomes, progress


def test_agent_worker_reports_one_line_failure_summary(monkeypatch, tmp_path):
    detail = 'Traceback (most recent call last):\n  File "event_index.py", line 21, in build_event_index\n    raise ValueError(...)\nValueError: run has no csv_flat file\n'
    worker, outcomes, progress = _worker_with_failing_build(monkeypatch, RuntimeError(detail), tmp_path)
    worker.run()
    assert outcomes == ["Analysis failed: ValueError: run has no csv_flat file"]
    assert detail.strip() in progress


def test_agent_worker_summarizes_failure_without_message(monkeypatch, tmp_path):
    worker, outcomes, progress = _worker_with_failing_build(monkeypatch, MemoryError(), tmp_path)
    worker.run()
    assert outcomes == ["Analysis failed: MemoryError"]
    assert progress[-1] == "MemoryError"


def test_agent_worker_reports_cancellation_instead_of_failure(monkeypatch, tmp_path):
    worker, outcomes, progress = _worker_with_failing_build(monkeypatch, RuntimeError("Analysis cancelled."), tmp_path)
    worker.cancelled.set()
    worker.run()
    assert outcomes == ["Analysis cancelled."]
