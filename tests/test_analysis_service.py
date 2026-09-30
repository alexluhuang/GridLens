from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil
import pytest

from gridlens.analysis.service import (
    AnalysisService, _lock_path, _terminate_group)
from gridlens.analysis.utilization import UtilizationBranchOptions
from gridlens.system import files, processes


def test_shared_service_builds_in_spawned_worker(agent_project):
    updates = []
    result = AnalysisService.build(agent_project / "runs/run_a", UtilizationBranchOptions(), updates.append)
    assert result.max_line_rows
    assert max(row["max_utilization_pct"] for row in result.max_line_rows) == 120
    assert updates


def test_waiting_shared_job_can_be_cancelled(agent_project):
    cancelled = threading.Event()
    with files.FileLock(_lock_path()):
        timer = threading.Timer(0.2, cancelled.set)
        timer.start()
        try:
            with pytest.raises(RuntimeError, match="cancelled"):
                AnalysisService.build(agent_project / "runs/run_a", UtilizationBranchOptions(), cancelled=cancelled)
        finally:
            timer.cancel()


def _sleeper_with_grandchild(pid_path: str) -> None:
    processes.own_process_group()
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
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True  # dead, waiting for its parent or init to reap it
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.02)
    return False


def _own_child_pids() -> set[int]:
    return {child.pid for child in psutil.Process().children()}


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
