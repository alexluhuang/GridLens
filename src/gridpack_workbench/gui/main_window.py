from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from gridpack_workbench.core.app_settings import AppSettings
from gridpack_workbench.core.project import Project, ProjectData
from gridpack_workbench.gui.analysis_tab import AnalysisTab
from gridpack_workbench.gui.help_tab import HelpTab
from gridpack_workbench.gui.project_tab import ProjectTab
from gridpack_workbench.gui.results_tab import ResultsTab
from gridpack_workbench.gui.run_tab import RunTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.project: Project | None = None
        self.project_data: ProjectData | None = None

        self.setWindowTitle(self.settings.app_name)
        self.resize(1240, 800)

        shell = QWidget()
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(14, 12, 14, 10)
        shell_layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(16)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        title = QLabel("GridPACK Workbench")
        title.setObjectName("appTitle")
        subtitle = QLabel("High-Performance Power Grid Simulation and Contingency Analysis")
        subtitle.setObjectName("appSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        header_layout.addLayout(title_stack, stretch=1)
        self.context_label = QLabel("No project loaded")
        self.context_label.setObjectName("contextLabel")
        self.context_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(self.context_label)
        shell_layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setTabPosition(QTabWidget.North)
        shell_layout.addWidget(self.tabs, stretch=1)
        self.setCentralWidget(shell)

        self.project_tab = ProjectTab(self.settings)
        self.run_tab = RunTab(self.settings)
        self.results_tab = ResultsTab()
        self.branch_analysis_tab = AnalysisTab()
        self.transformer_analysis_tab = AnalysisTab(transformer_analysis=True)
        self.analysis_tab = self.branch_analysis_tab
        self.help_tab = HelpTab()

        self.tabs.addTab(self.project_tab, "Project")
        self.tabs.addTab(self.run_tab, "Run")
        self.tabs.addTab(self.results_tab, "Results")
        self.tabs.addTab(self.branch_analysis_tab, "Branch Analysis")
        self.tabs.addTab(self.transformer_analysis_tab, "Transformer Analysis")
        self.tabs.addTab(self.help_tab, "Help")

        self.project_tab.project_changed.connect(self.on_project_changed)
        self.run_tab.run_finished.connect(self.on_run_finished)
        self.results_tab.run_selected.connect(self.branch_analysis_tab.select_run)
        self.results_tab.run_selected.connect(self.transformer_analysis_tab.select_run)

        self.statusBar().showMessage("Create or open a project to begin.")

    def on_project_changed(self, project: Project, project_data: ProjectData) -> None:
        self.project = project
        self.project_data = project_data
        self.run_tab.set_project(project, project_data)
        self.results_tab.set_project(project)
        self.branch_analysis_tab.set_project(project)
        self.transformer_analysis_tab.set_project(project)
        self.context_label.setText(f"{project_data.name}")
        self.statusBar().showMessage(f"Project loaded: {project_data.name}")

    def on_run_finished(self, run_dir: object) -> None:
        path = Path(str(run_dir))
        self.results_tab.refresh_runs(select_run=path)
        self.branch_analysis_tab.refresh_runs(select_run=path)
        self.transformer_analysis_tab.refresh_runs(select_run=path)
        self.tabs.setCurrentWidget(self.results_tab)
        project_name = self.project_data.name if self.project_data else "Project"
        self.context_label.setText(f"{project_name} · latest run {path.name}")
        self.statusBar().showMessage(f"Run finished: {path.name}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.settings.save()
        event.accept()
