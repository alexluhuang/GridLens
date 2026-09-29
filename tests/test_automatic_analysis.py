"""A completed GridPACK run from the Run tab prepares its branch and transformer analysis by itself."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time

from PySide6.QtWidgets import QApplication, QMessageBox

from gridlens.core.project import Project
from gridlens.gui import analysis_tab
from gridlens.gui.analysis_tab import AnalysisTab
from gridlens.gui.main_window import MainWindow


def _wait_for(tab: AnalysisTab, app: QApplication, seconds: float = 60) -> None:
    """Let a tab's background builds, including any queued one, run to the end."""
    deadline = time.monotonic() + seconds
    while (tab.analysis_worker is not None or tab._pending_run is not None) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert tab.analysis_worker is None, "the analysis did not finish"


def _no_dialogs(monkeypatch) -> list:
    """Record any dialog a tab tries to show; an automatic build must show none."""
    shown = []
    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *args, name=name: shown.append((name, args[1:3])))
    return shown


def test_main_window_analyzes_only_a_completed_run(agent_project, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    project = Project("Synthetic Project", agent_project)
    for tab in (window.results_tab, window.branch_analysis_tab, window.transformer_analysis_tab):
        tab.set_project(project)
    requested = []
    for tab in (window.branch_analysis_tab, window.transformer_analysis_tab):
        monkeypatch.setattr(tab, "analyze_run", lambda run, tab=tab: requested.append((tab.transformer_analysis, run.name)))
    window.on_run_finished(agent_project / "runs/run_a")
    assert requested == [(False, "run_a"), (True, "run_a")]
    assert "Preparing its branch and transformer analysis" in window.statusBar().currentMessage()
    (agent_project / "runs/run_b/status.json").write_text('{"status": "failed"}')
    window.on_run_finished(agent_project / "runs/run_b")
    assert requested == [(False, "run_a"), (True, "run_a")]
    for tab in (window.agent_tab, window.branch_analysis_tab, window.transformer_analysis_tab):
        assert tab.shutdown()
    window.deleteLater()
    app.processEvents()


def test_analyze_run_selects_the_run_and_charts_it_without_dialogs(agent_project, monkeypatch):
    app = QApplication.instance() or QApplication([])
    shown = _no_dialogs(monkeypatch)
    tabs = [AnalysisTab(), AnalysisTab(transformer_analysis=True)]
    for tab in tabs:
        tab.set_project(Project("Synthetic Project", agent_project))
        tab.analyze_run(agent_project / "runs/run_a")
        assert tab.selected_run_dir().name == "run_a"
    for tab in tabs:
        _wait_for(tab, app)
    assert len(tabs[0].max_line_rows) == 3
    assert len(tabs[1].max_line_rows) == 1
    assert shown == []
    for tab in tabs:
        tab.deleteLater()
    app.processEvents()


def test_a_run_finishing_during_a_build_is_analyzed_next(agent_project, monkeypatch):
    app = QApplication.instance() or QApplication([])
    _no_dialogs(monkeypatch)
    tab = AnalysisTab()
    tab.set_project(Project("Synthetic Project", agent_project))
    tab.analyze_run(agent_project / "runs/run_a")
    tab.analyze_run(agent_project / "runs/run_b")
    assert tab._pending_run.name == "run_b"
    _wait_for(tab, app)
    assert tab.selected_run_dir().name == "run_b"
    # The fixture's run_b loads each line 10 points more than run_a.
    assert max(row["max_utilization_pct"] for row in tab.max_line_rows) == 130
    tab.deleteLater()
    app.processEvents()


def test_an_automatic_build_that_fails_says_so_in_the_status_line(agent_project, monkeypatch):
    app = QApplication.instance() or QApplication([])
    shown = _no_dialogs(monkeypatch)

    def fail(*_args):
        # AnalysisService re-raises the build worker's traceback as the message.
        raise RuntimeError('Traceback (most recent call last):\n  File "event_index.py", line 21\nValueError: run has no csv_flat file')

    monkeypatch.setattr(analysis_tab, "_build_analysis_result_in_process", fail)
    tab = AnalysisTab()
    tab.set_project(Project("Synthetic Project", agent_project))
    tab.analyze_run(agent_project / "runs/run_a")
    _wait_for(tab, app)
    assert shown == []
    assert tab.status_label.text() == "The automatic analysis failed: ValueError: run has no csv_flat file. Click Generate Graphs to try again."
    tab.generate_graphs()
    _wait_for(tab, app)
    assert [name for name, _ in shown] == ["critical"]
    tab.deleteLater()
    app.processEvents()
