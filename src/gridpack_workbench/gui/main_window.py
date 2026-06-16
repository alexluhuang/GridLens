from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QTabWidget

from gridpack_workbench.core.app_settings import AppSettings
from gridpack_workbench.gui.analysis_tab import AnalysisTab
from gridpack_workbench.gui.help_tab import HelpTab
from gridpack_workbench.gui.project_tab import ProjectTab
from gridpack_workbench.gui.results_tab import ResultsTab
from gridpack_workbench.gui.run_tab import RunTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.project = None
        self.project_data = None

        self.setWindowTitle(self.settings.app_name)
        self.resize(1180, 760)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.setCentralWidget(self.tabs)

        self.project_tab = ProjectTab(self.settings)
        self.run_tab = RunTab(self.settings)
        self.results_tab = ResultsTab()
        self.analysis_tab = AnalysisTab(self.settings)
        self.help_tab = HelpTab()

        self.tabs.addTab(self.project_tab, "Project")
        self.tabs.addTab(self.run_tab, "Run")
        self.tabs.addTab(self.results_tab, "Results")
        self.tabs.addTab(self.analysis_tab, "Analysis")
        self.tabs.addTab(self.help_tab, "Workflow")

        self.project_tab.project_changed.connect(self.on_project_changed)
        self.run_tab.run_finished.connect(self.on_run_finished)
        self.results_tab.run_selected.connect(self.analysis_tab.select_run)

        self.statusBar().showMessage("Create or open a project to begin.")

    def on_project_changed(self, project: object, project_data: object) -> None:
        self.project = project
        self.project_data = project_data
        self.run_tab.set_project(project, project_data)
        self.results_tab.set_project(project)
        self.analysis_tab.set_project(project)
        self.statusBar().showMessage(f"Project loaded: {project_data.name}")

    def on_run_finished(self, run_dir: object) -> None:
        path = Path(str(run_dir))
        self.results_tab.refresh_runs(select_run=path)
        self.analysis_tab.refresh_runs(select_run=path)
        self.tabs.setCurrentWidget(self.results_tab)
        self.statusBar().showMessage(f"Run finished: {path.name}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.settings.save()
        event.accept()
