from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from queue import Empty
import signal
import threading
import traceback

from gridlens.analysis.interactive import build_interactive_analysis_result
from gridlens.analysis.progress import AnalysisProgress
from gridlens.analysis.utilization import UtilizationBranchOptions
from gridlens.system import files, paths, processes


def _build(run_dir, options, messages, indexed, rebuild):
    processes.own_process_group()
    try:
        result = build_interactive_analysis_result(run_dir, options, lambda update: messages.put(("progress", update)), rebuild=rebuild)
        if indexed:
            from gridlens.analysis.event_index import build_event_index

            build_event_index(run_dir, progress=lambda update: messages.put(("progress", update)))
        messages.put(("result", result))
    except Exception:
        messages.put(("error", traceback.format_exc()))


def _terminate_group(process) -> None:
    # On POSIX _build calls os.setsid(), so the worker pid is also its group
    # id: signal the whole group so a grandchild (an index writer, a helper
    # subprocess) cannot outlive a cancelled build. Windows has no such
    # groups, so the worker's process tree is killed instead.
    if processes.WINDOWS:
        if process.is_alive():
            processes.kill_tree(process.pid)
        process.join()
        return
    if process.is_alive():
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            process.terminate()  # killed before os.setsid() took effect, so it has no group of its own
        process.join(1)
        if process.is_alive():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                process.kill()
    process.join()


def _lock_path() -> Path:
    """Return the lock file that lets one analysis build run at a time.

    Every GridLens process of the user, the GUI and the job workers alike,
    must name the same file.
    """
    if os.name == "nt":
        return paths.shared_temp_dir() / "gridlens-analysis.lock"
    return paths.shared_temp_dir() / f"gridlens-analysis-{os.getuid()}.lock"


def _wait_for_lock(lock: files.FileLock, progress,
                   cancelled: threading.Event) -> None:
    """Take the build lock, reporting the wait and giving up if cancelled."""
    waiting = AnalysisProgress("parse", "Waiting for another analysis build…")
    while not lock.acquire(blocking=False):
        if progress:
            progress(waiting)
        if cancelled.wait(0.2):
            raise RuntimeError("Analysis cancelled.")


class AnalysisService:
    """Serialize analysis builds across GUI tabs and processes, with cancellable workers."""

    @staticmethod
    def build(run_dir: Path, options: UtilizationBranchOptions, progress=None, cancelled=None, *, indexed: bool = False, rebuild: bool = False):
        cancelled = cancelled or threading.Event()
        lock = files.FileLock(_lock_path())
        _wait_for_lock(lock, progress, cancelled)
        try:
            if cancelled.is_set():
                raise RuntimeError("Analysis cancelled.")
            context = multiprocessing.get_context("spawn")
            messages = context.Queue()
            process = context.Process(target=_build, args=(run_dir, options, messages, indexed, rebuild))
            process.start()
            try:
                while True:
                    if cancelled.is_set():
                        raise RuntimeError("Analysis cancelled.")
                    try:
                        kind, value = messages.get(timeout=0.1)
                    except Empty:
                        if not process.is_alive():
                            raise RuntimeError(f"Analysis worker exited with code {process.exitcode}.")
                        continue
                    if kind == "progress" and progress:
                        progress(value)
                    elif kind == "error":
                        raise RuntimeError(value)
                    elif kind == "result":
                        return value
            finally:
                _terminate_group(process)
                messages.close()
        finally:
            lock.release()
