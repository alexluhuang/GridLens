from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QThread, Signal

from gridlens.analysis.service import AnalysisService
from gridlens.analysis.utilization import UtilizationBranchOptions


class AgentAnalysisWorker(QThread):
    progress = Signal(str)
    outcome = Signal(str)

    def __init__(self, runs: list[Path], indexed: bool, parent) -> None:
        super().__init__(parent)
        self.runs = runs
        self.indexed = indexed
        self.cancelled = threading.Event()

    def run(self) -> None:
        try:
            for run in self.runs:
                self.progress.emit(f"Building analysis for {run.name}…")
                AnalysisService.build(run, UtilizationBranchOptions(), lambda update: self.progress.emit(update.detail), self.cancelled, indexed=self.indexed, rebuild=True)
            self.outcome.emit("Analysis ready. Ask your question again.")
        except Exception as exc:
            if self.cancelled.is_set():
                self.outcome.emit("Analysis cancelled.")
                return
            # AnalysisService re-raises the worker traceback verbatim; outcome lands in a one-line label,
            # so keep only the last line there and send the full detail to the activity pane.
            detail = str(exc).strip()
            summary = (detail.splitlines() or [type(exc).__name__])[-1][:200]
            self.progress.emit(detail or type(exc).__name__)
            self.outcome.emit(f"Analysis failed: {summary}")
