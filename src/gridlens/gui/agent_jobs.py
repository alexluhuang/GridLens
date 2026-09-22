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
            self.outcome.emit("Analysis cancelled." if self.cancelled.is_set() else f"Analysis failed: {exc}")
