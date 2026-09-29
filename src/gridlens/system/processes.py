"""Starting, watching, and stopping child processes on Linux and Windows.

GridLens runs command-line programs, such as docker, Hermes, and its own job
workers, and must be able to stop each one with everything it started. On
POSIX a child started in a new session leads its own process group, and one
signal to the group reaches every descendant. Windows has no such groups: a
new process group there only routes console events, so stopping a program
means terminating each process of its tree. A windowed program on Windows
also opens a console window for every console child it starts, unless it
asks it not to.
"""
from __future__ import annotations

import os
import signal
import subprocess

import psutil

WINDOWS = os.name == "nt"
# Two start times closer than this belong to the same process. psutil
# reports Linux start times in clock ticks, a hundredth of a second.
_START_TIME_TOLERANCE_SECONDS = 1.0
_EXIT_WAIT_SECONDS = 2.0


def no_window_options() -> dict:
    """Return Popen arguments that keep a console child's window hidden."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def new_group_options() -> dict:
    """Return Popen arguments that start a child in a group of its own.

    `terminate` stops such a child together with everything it starts.
    """
    if WINDOWS:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def start_detached(argv: list[str], **options) -> subprocess.Popen:
    """Start a child that keeps running after the process that started it.

    On Windows the child also leaves any job object of its parent, where the
    job allows it, so that closing the parent's job does not end it.
    """
    if not WINDOWS:
        return subprocess.Popen(argv, start_new_session=True, **options)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        breakaway = flags | subprocess.CREATE_BREAKAWAY_FROM_JOB
        return subprocess.Popen(argv, creationflags=breakaway, **options)
    except PermissionError:
        # The parent's job forbids breaking away; the child stays in it.
        return subprocess.Popen(argv, creationflags=flags, **options)


def own_process_group() -> None:
    """Make the calling process lead a new process group, on POSIX."""
    if not WINDOWS:
        os.setsid()


def terminate(process: subprocess.Popen, grace: float = 1.0) -> None:
    """Stop a child started with `new_group_options` and all it started.

    On POSIX the group gets SIGTERM, then SIGKILL after grace seconds, and
    that reaches the child's descendants even after the child has exited.
    On Windows every process of the child's tree is terminated at once.
    """
    if WINDOWS:
        kill_tree(process.pid)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=_EXIT_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def kill_tree(pid: int) -> None:
    """Kill the process pid and every process it started, at once.

    On POSIX pid must lead its own process group. The caller must know that
    pid still names its child, by holding the child's Popen or by checking
    `pid_alive` with the child's start time, because a process id is reused
    once its process is gone.
    """
    if not WINDOWS:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return
    tree = _windows_tree(pid)
    for member in tree:
        try:
            member.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(tree, timeout=_EXIT_WAIT_SECONDS)


def start_time(pid: int) -> float | None:
    """Return when the process pid started, in seconds since the epoch."""
    try:
        return psutil.Process(int(pid)).create_time()
    except (psutil.Error, TypeError, ValueError):
        return None


def pid_alive(pid: object, started: float | None = None) -> bool:
    """Return whether the process pid is running.

    With started, the start time recorded when the process was launched, a
    different process that has since been given the same id does not count.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    running = _windows_alive(pid) if WINDOWS else _posix_alive(pid)
    if not running or started is None:
        return running
    actual = start_time(pid)
    if actual is None:
        return running
    return abs(actual - float(started)) <= _START_TIME_TOLERANCE_SECONDS


def _posix_alive(pid: int) -> bool:
    """Return whether pid is running, reaping it first if it is our child.

    A child that has exited stays a zombie until its parent reaps it, and a
    zombie still answers signal 0.
    """
    try:
        finished, _status = os.waitpid(pid, os.WNOHANG)
        if finished:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_alive(pid: int) -> bool:
    """Return whether pid is running, on Windows."""
    try:
        process = psutil.Process(pid)
        return process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _windows_tree(pid: int) -> list[psutil.Process]:
    """Return the process pid, if it runs, and all its descendants.

    Windows does not reparent a process whose parent exits, so the
    descendants of a parent that has gone are found through their recorded
    parent ids.
    """
    try:
        parent = psutil.Process(pid)
        return [parent, *parent.children(recursive=True)]
    except psutil.Error:
        return _orphaned_descendants(pid)


def _orphaned_descendants(pid: int) -> list[psutil.Process]:
    """Return the processes descended from pid, which no longer runs."""
    children: dict[int, list[psutil.Process]] = {}
    for process in psutil.process_iter(["ppid"]):
        parent_id = process.info["ppid"]
        children.setdefault(parent_id, []).append(process)
    descendants = []
    seen = {pid}
    pending = list(children.get(pid, []))
    while pending:
        process = pending.pop()
        if process.pid in seen:
            continue
        seen.add(process.pid)
        descendants.append(process)
        pending.extend(children.get(process.pid, []))
    return descendants
