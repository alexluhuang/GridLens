from __future__ import annotations

import fcntl
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


def _build(run_dir, options, messages, indexed, rebuild):
    os.setsid()
    try:
        result = build_interactive_analysis_result(run_dir, options, lambda update: messages.put(("progress", update)), rebuild=rebuild)
        if indexed:
            from gridlens.analysis.event_index import build_event_index

            build_event_index(run_dir, progress=lambda update: messages.put(("progress", update)))
        messages.put(("result", result))
    except Exception:
        messages.put(("error", traceback.format_exc()))


class AnalysisService:
    """Serialize analysis builds across GUI tabs and processes, with cancellable workers."""

    @staticmethod
    def build(run_dir: Path, options: UtilizationBranchOptions, progress=None, cancelled=None, *, indexed: bool = False, rebuild: bool = False):
        cancelled = cancelled or threading.Event()
        lock_path = Path("/tmp") / f"gridlens-analysis-{os.getuid()}.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if progress:
                        progress(AnalysisProgress("parse", "Waiting for another analysis build…"))
                    if cancelled.wait(0.2):
                        raise RuntimeError("Analysis cancelled.")
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
                if process.is_alive():
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        process.terminate()
                    process.join(1)
                    if process.is_alive():
                        process.kill()
                process.join()
                messages.close()
