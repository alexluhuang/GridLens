"""Child processes start in their own group and stop with all they started.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import types

import psutil
import pytest

from gridlens.system import processes

# A child that starts a grandchild, records both pids, and waits.
PARENT_SCRIPT = (
    "import subprocess, sys, time; from pathlib import Path; "
    "child = subprocess.Popen([sys.executable, '-c', "
    "'import time; time.sleep(120)']); "
    "Path(sys.argv[1]).write_text(f'{child.pid}'); time.sleep(120)"
)


def _gone(pid: int) -> bool:
    """Wait briefly for pid to exit; a zombie awaiting its reaper counts."""
    for _ in range(250):
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.02)
    return False


def _grandchild_pid(pid_file: Path) -> int:
    for _ in range(500):
        if pid_file.is_file() and pid_file.read_text():
            return int(pid_file.read_text())
        time.sleep(0.02)
    pytest.fail("the child never started its grandchild")


def test_terminate_stops_a_child_and_its_grandchild(tmp_path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    child = subprocess.Popen(
        [sys.executable, "-c", PARENT_SCRIPT, str(pid_file)],
        **processes.new_group_options())
    grandchild = _grandchild_pid(pid_file)

    processes.terminate(child, grace=0.2)

    assert child.poll() is not None
    assert _gone(grandchild)


def test_kill_tree_stops_a_detached_worker_by_pid(tmp_path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    worker = processes.start_detached(
        [sys.executable, "-c", PARENT_SCRIPT, str(pid_file)])
    grandchild = _grandchild_pid(pid_file)

    processes.kill_tree(worker.pid)
    worker.wait(timeout=10)

    assert _gone(grandchild)


@pytest.mark.skipif(os.name == "nt", reason="Windows has no sessions")
def test_detached_workers_lead_their_own_session() -> None:
    worker = processes.start_detached(
        [sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert os.getsid(worker.pid) == worker.pid
    finally:
        processes.terminate(worker)


def test_pid_alive_tells_running_from_finished_processes() -> None:
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()

    assert processes.pid_alive(os.getpid())
    assert not processes.pid_alive(finished.pid)
    assert not processes.pid_alive(None)
    assert not processes.pid_alive("not a pid")


def test_pid_alive_rejects_a_process_that_reused_the_pid() -> None:
    started = processes.start_time(os.getpid())

    assert processes.pid_alive(os.getpid(), started)
    assert not processes.pid_alive(os.getpid(), started - 3600)


def test_orphaned_descendants_follow_recorded_parent_ids(monkeypatch) -> None:
    def fake(pid, ppid):
        return types.SimpleNamespace(pid=pid, info={"ppid": ppid})

    table = [fake(10, 1), fake(11, 10), fake(12, 11), fake(13, 2),
             fake(14, 14)]
    monkeypatch.setattr(processes.psutil, "process_iter", lambda attrs: table)

    found = {process.pid for process in processes._orphaned_descendants(10)}

    assert found == {11, 12}


@pytest.mark.skipif(os.name != "nt", reason="Windows creation flags")
def test_windows_children_open_no_console_window() -> None:
    flags = processes.new_group_options()["creationflags"]

    assert flags & subprocess.CREATE_NO_WINDOW
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert processes.no_window_options() == {
        "creationflags": subprocess.CREATE_NO_WINDOW}


@pytest.mark.skipif(os.name == "nt", reason="POSIX sessions")
def test_posix_children_start_a_new_session() -> None:
    assert processes.new_group_options() == {"start_new_session": True}
    assert processes.no_window_options() == {}
