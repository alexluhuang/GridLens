from __future__ import annotations

from pathlib import Path
import traceback

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gridlens.core.app_settings import AppSettings
from gridlens.core.project import Project, ProjectData
from gridlens.core.validation import ValidationError
from gridlens.gui.run_view_models import (
    RunFormValues,
    apply_run_form_values_to_settings,
    build_gridpack_run_request,
    validate_run_form_values,
)
from gridlens.gui.theme import set_button_role
from gridlens.runner.docker_probe import docker_client_available, docker_engine_available, image_exists
from gridlens.runner.gridpack_runner import GridpackRunRequest, GridpackRunResult, run_gridpack_case


class RunWorker(QThread):
    log_line = Signal(str)
    finished_run = Signal(object)
    failed_run = Signal(str)

    def __init__(self, request: GridpackRunRequest) -> None:
        super().__init__()
        self.request = request

    def run(self) -> None:
        try:
            result = run_gridpack_case(self.request, log_callback=self.log_line.emit)
            self.finished_run.emit(result)
        except Exception:
            self.failed_run.emit(traceback.format_exc())


class RunTab(QWidget):
    run_finished = Signal(object)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.project: Project | None = None
        self.project_data: ProjectData | None = None
        self.worker: RunWorker | None = None
        self.last_run_dir: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        config_box = QGroupBox("Container Run Settings")
        form = QFormLayout(config_box)
        self.image = QLineEdit(settings.default_gridpack_image)
        self.executable = QLineEdit(settings.default_executable)
        self.mpi_processes = QSpinBox()
        self.mpi_processes.setRange(1, 4096)
        self.mpi_processes.setValue(settings.default_mpi_processes)
        self.memory_limit = QLineEdit(settings.memory_limit)
        self.memory_limit.setPlaceholderText("Optional, for example 8g")
        self.extra_args = QLineEdit(settings.extra_docker_args)
        self.extra_args.setPlaceholderText("Optional Docker args, parsed safely")

        self.pull_policy = QComboBox()
        self.pull_policy.addItems(["never", "missing", "always"])
        self.pull_policy.setCurrentText(settings.docker_pull_policy)

        self.network_none = QCheckBox("Disable network inside the run container")
        self.network_none.setChecked(settings.docker_network_mode == "none")
        self.use_platform = QCheckBox("Use detected platform flag")
        self.use_platform.setChecked(settings.use_platform_flag)
        self.use_host_user = QCheckBox("Write output files as the current Linux user")
        self.use_host_user.setChecked(settings.use_host_user)

        form.addRow("Docker image", self.image)
        form.addRow("GridPACK executable", self.executable)
        form.addRow("MPI processes", self.mpi_processes)
        form.addRow("Docker pull policy", self.pull_policy)
        form.addRow("Memory limit", self.memory_limit)
        form.addRow("Extra Docker args", self.extra_args)
        form.addRow("", self.network_none)
        form.addRow("", self.use_platform)
        form.addRow("", self.use_host_user)

        action_row = QHBoxLayout()
        self.check_button = QPushButton("Check Docker")
        set_button_role(self.check_button, "secondary")
        self.check_button.clicked.connect(self.check_docker)
        self.run_button = QPushButton("Run GridPACK")
        set_button_role(self.run_button, "primary")
        self.run_button.clicked.connect(self.start_run)
        self.run_button.setEnabled(False)
        self.open_run_button = QPushButton("Open Run Folder")
        set_button_role(self.open_run_button, "secondary")
        self.open_run_button.clicked.connect(self.open_last_run)
        self.open_run_button.setEnabled(False)
        action_row.addWidget(self.check_button)
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.open_run_button)
        action_row.addStretch()

        self.project_label = QLabel("No project loaded.")
        self.project_label.setObjectName("contextLabel")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        layout.addWidget(self.project_label)
        layout.addWidget(config_box)
        layout.addLayout(action_row)
        layout.addWidget(QLabel("Run log"))
        layout.addWidget(self.log, stretch=1)

    def set_project(self, project: Project, project_data: ProjectData) -> None:
        self.project = project
        self.project_data = project_data
        self.project_label.setText(f"Ready: {project_data.name} ({project.root_dir})")
        self.run_button.setEnabled(True)

    def check_docker(self) -> None:
        client = docker_client_available()
        engine = docker_engine_available()
        image = image_exists(self.image.text().strip())

        lines = [
            f"Docker client: {'OK' if client.ok else 'Problem'} - {client.message}",
            f"Docker engine: {'OK' if engine.ok else 'Problem'} - {engine.message}",
            f"GridPACK image: {'OK' if image.ok else 'Problem'} - {image.message}",
        ]
        message = "\n".join(lines)
        self.append_log(message)
        if client.ok and engine.ok and image.ok:
            QMessageBox.information(self, "Docker check", message)
        else:
            QMessageBox.warning(self, "Docker check", message)

    def start_run(self) -> None:
        if not self.project or not self.project_data:
            QMessageBox.warning(self, "No project", "Create or open a project first.")
            return

        values = self._run_form_values()
        try:
            validate_run_form_values(values)
        except ValidationError as exc:
            QMessageBox.warning(self, "Run settings need attention", str(exc))
            return

        apply_run_form_values_to_settings(self.settings, values)
        self.settings.save()

        run_dir = self.project.create_run_folder()
        request = build_gridpack_run_request(self.project_data, run_dir, values)

        self.log.clear()
        self.append_log(f"Created run folder: {run_dir}")
        self.run_button.setEnabled(False)
        self.open_run_button.setEnabled(False)

        self.worker = RunWorker(request)
        self.worker.log_line.connect(self.append_log)
        self.worker.finished_run.connect(self.on_finished)
        self.worker.failed_run.connect(self.on_failed)
        self.worker.start()

    def append_log(self, text: str) -> None:
        self.log.append(text.rstrip())

    def _run_form_values(self) -> RunFormValues:
        return RunFormValues(
            image=self.image.text(),
            executable=self.executable.text(),
            mpi_processes=self.mpi_processes.value(),
            pull_policy=self.pull_policy.currentText(),
            network_disabled=self.network_none.isChecked(),
            use_platform_flag=self.use_platform.isChecked(),
            use_host_user=self.use_host_user.isChecked(),
            memory_limit=self.memory_limit.text(),
            extra_docker_args=self.extra_args.text(),
        )

    def on_finished(self, result: GridpackRunResult) -> None:
        self.run_button.setEnabled(True)
        self.last_run_dir = result.run_dir
        self.open_run_button.setEnabled(True)
        if result.return_code == 0:
            self.append_log("Run completed successfully.")
            QMessageBox.information(self, "Run completed", "GridPACK completed successfully.")
        else:
            self.append_log(f"Run failed with return code {result.return_code}.")
            QMessageBox.warning(self, "Run failed", f"GridPACK exited with return code {result.return_code}.")
        self.run_finished.emit(result.run_dir)

    def on_failed(self, error_text: str) -> None:
        self.run_button.setEnabled(True)
        self.append_log(error_text)
        QMessageBox.critical(self, "Run error", error_text)

    def open_last_run(self) -> None:
        if self.last_run_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_run_dir)))
