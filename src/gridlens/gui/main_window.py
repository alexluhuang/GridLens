from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QSizePolicy, QTabWidget, QVBoxLayout, QWidget

from gridlens.core.app_settings import AppSettings
from gridlens.core.project import Project, ProjectData
from gridlens.gui.analysis_tab import AnalysisTab
from gridlens.gui.configuration_tab import ConfigurationTab
from gridlens.gui.notes_tab import NotesTab
from gridlens.gui.project_tab import ProjectTab
from gridlens.gui.results_tab import ResultsTab
from gridlens.gui.run_tab import RunTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.project: Project | None = None
        self.project_data: ProjectData | None = None

        self.setWindowTitle(self.settings.app_name)
        self.resize(1280, 840)
        self.setMinimumSize(760, 560)

        shell = QWidget()
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(12, 12, 12, 10)
        shell_layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(12)
        logo = QSvgWidget(str(Path(__file__).resolve().parents[1] / "resources" / "gridlens.svg"))
        logo.setObjectName("headerLogo")
        logo.setFixedSize(QSize(40, 40))
        logo.setToolTip("GridLens")
        header_layout.addWidget(logo)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        title = QLabel("GridLens")
        title.setObjectName("appTitle")
        subtitle = QLabel("High-Performance Power Grid Simulation and Contingency Analysis")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(True)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        header_layout.addLayout(title_stack, stretch=1)
        self.context_label = QLabel("No project loaded")
        self.context_label.setObjectName("headerContextLabel")
        self.context_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.context_label.setWordWrap(True)
        self.context_label.setMaximumWidth(380)
        self.context_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        header_layout.addWidget(self.context_label)
        shell_layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        shell_layout.addWidget(self.tabs, stretch=1)
        self.setCentralWidget(shell)

        self.project_tab = ProjectTab(self.settings)
        self.configuration_tab = ConfigurationTab()
        self.run_tab = RunTab(self.settings)
        self.results_tab = ResultsTab()
        self.branch_analysis_tab = AnalysisTab()
        self.transformer_analysis_tab = AnalysisTab(transformer_analysis=True)
        self.analysis_tab = self.branch_analysis_tab
        self.notes_tab = NotesTab()

        self.tabs.addTab(self.project_tab, "Project")
        self.tabs.addTab(self.configuration_tab, "Configuration")
        self.tabs.addTab(self.run_tab, "Run")
        self.tabs.addTab(self.results_tab, "Results")
        self.tabs.addTab(self.branch_analysis_tab, "Branch Analysis")
        self.tabs.addTab(self.transformer_analysis_tab, "Transformer Analysis")
        self.tabs.addTab(self.notes_tab, "Notes")
        self.tabs.setTabToolTip(0, "Create a project and add GridPACK input files.")
        self.tabs.setTabToolTip(1, "Generate or update the GridPACK XML configuration.")
        self.tabs.setTabToolTip(2, "Check Docker and run the selected case.")
        self.tabs.setTabToolTip(3, "Review, open, or export completed runs.")
        self.tabs.setTabToolTip(4, "Analyze non-transformer branch utilization.")
        self.tabs.setTabToolTip(5, "Analyze transformer utilization.")
        self.tabs.setTabToolTip(6, "Read analysis assumptions and data notes.")

        self.project_tab.project_changed.connect(self.on_project_changed)
        self.configuration_tab.project_changed.connect(self.on_project_changed)
        self.run_tab.run_finished.connect(self.on_run_finished)
        self.results_tab.run_selected.connect(self.branch_analysis_tab.select_run)
        self.results_tab.run_selected.connect(self.transformer_analysis_tab.select_run)

        self.statusBar().showMessage("Create or open a project to begin.")

    def on_project_changed(self, project: Project, project_data: ProjectData) -> None:
        self.project = project
        self.project_data = project_data
        self.project_tab.set_project(project, project_data)
        self.configuration_tab.set_project(project, project_data)
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
