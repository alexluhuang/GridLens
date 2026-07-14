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
    QProgressBar,
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
from gridlens.gui.theme import configure_form_layout, set_button_role, set_context_label
from gridlens.runner.docker_probe import docker_client_available, docker_engine_available, image_exists
from gridlens.runner.gridpack_runner import (
    GridpackRunRequest,
    GridpackRunResult,
    GridpackTerminationResult,
    run_gridpack_case,
    terminate_gridpack_run,
)
from gridlens.runner.run_progress import GridpackProgressParser


class RunWorker(QThread):
    log_line = Signal(str)
    progress = Signal(object)
    finished_run = Signal(object)
    failed_run = Signal(str)

    def __init__(self, request: GridpackRunRequest) -> None:
        super().__init__()
        self.request = request

    def run(self) -> None:
        parser = GridpackProgressParser()

        def on_line(line: str) -> None:
            self.log_line.emit(line)
            update = parser.feed(line)
            if update is not None:
                self.progress.emit(update)

        try:
            result = run_gridpack_case(self.request, log_callback=on_line)
            self.finished_run.emit(result)
        except Exception:
            self.failed_run.emit(traceback.format_exc())


class TerminateWorker(QThread):
    finished_terminate = Signal(object)
    failed_terminate = Signal(str)

    def __init__(self, container_name: str) -> None:
        super().__init__()
        self.container_name = container_name

    def run(self) -> None:
        try:
            result = terminate_gridpack_run(self.container_name)
            self.finished_terminate.emit(result)
        except Exception:
            self.failed_terminate.emit(traceback.format_exc())


class RunTab(QWidget):
    run_finished = Signal(object)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.project: Project | None = None
        self.project_data: ProjectData | None = None
        self.worker: RunWorker | None = None
        self.terminate_worker: TerminateWorker | None = None
        self.active_request: GridpackRunRequest | None = None
        self.termination_requested = False
        self.last_run_dir: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        config_box = QGroupBox("Container Run Settings")
        form = QFormLayout(config_box)
        configure_form_layout(form)
        self.image = QLineEdit(settings.default_gridpack_image)
        self.image.setToolTip("Docker image used to run GridPACK.")
        self.executable = QLineEdit(settings.default_executable)
        self.executable.setToolTip("Executable path or command inside the GridPACK container.")
        self.mpi_processes = QSpinBox()
        self.mpi_processes.setRange(1, 4096)
        self.mpi_processes.setValue(settings.default_mpi_processes)
        self.mpi_processes.setToolTip("MPI process count passed to the run command.")
        self.memory_limit = QLineEdit(settings.memory_limit)
        self.memory_limit.setPlaceholderText("Optional, for example 8g")
        self.memory_limit.setToolTip("Optional Docker memory limit, such as 8g.")
        self.extra_args = QLineEdit(settings.extra_docker_args)
        self.extra_args.setPlaceholderText("Optional Docker args, parsed safely")
        self.extra_args.setToolTip("Optional Docker arguments parsed without invoking a shell.")

        self.pull_policy = QComboBox()
        self.pull_policy.addItems(["never", "missing", "always"])
        self.pull_policy.setCurrentText(settings.docker_pull_policy)
        self.pull_policy.setToolTip("Controls whether GridLens tries to pull the Docker image.")

        self.network_none = QCheckBox("Disable network inside the run container")
        self.network_none.setChecked(settings.docker_network_mode == "none")
        self.network_none.setToolTip("Run the container with Docker network mode set to none.")
        self.use_platform = QCheckBox("Use detected platform flag")
        self.use_platform.setChecked(settings.use_platform_flag)
        self.use_platform.setToolTip("Pass the detected Docker platform flag when needed.")
        self.use_host_user = QCheckBox("Write output files as the current Linux user")
        self.use_host_user.setChecked(settings.use_host_user)
        self.use_host_user.setToolTip("Map container writes to the current Linux user.")

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
        action_row.setSpacing(8)
        self.check_button = QPushButton("Check Docker")
        set_button_role(self.check_button, "secondary")
        self.check_button.setToolTip("Check Docker client, engine, and image availability.")
        self.check_button.clicked.connect(self.check_docker)
        self.run_button = QPushButton("Run GridPACK")
        set_button_role(self.run_button, "primary")
        self.run_button.setToolTip("Start a GridPACK Docker run for the current project.")
        self.run_button.clicked.connect(self.start_run)
        self.run_button.setEnabled(False)
        self.terminate_button = QPushButton("Terminate")
        set_button_role(self.terminate_button, "destructive")
        self.terminate_button.setToolTip("Request termination of the active Docker run.")
        self.terminate_button.clicked.connect(self.terminate_run)
        self.terminate_button.setEnabled(False)
        self.open_run_button = QPushButton("Open Run Folder")
        set_button_role(self.open_run_button, "secondary")
        self.open_run_button.setToolTip("Open the latest completed run folder.")
        self.open_run_button.clicked.connect(self.open_last_run)
        self.open_run_button.setEnabled(False)
        action_row.addWidget(self.check_button)
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.terminate_button)
        action_row.addWidget(self.open_run_button)
        action_row.addStretch()

        self.project_label = QLabel("No project loaded.")
        set_context_label(self.project_label)

        self.progress_group = QGroupBox("Run Progress")
        progress_layout = QVBoxLayout(self.progress_group)
        progress_layout.setContentsMargins(12, 10, 12, 12)
        progress_layout.setSpacing(6)
        self.progress_label = QLabel("Waiting to start...")
        self.progress_label.setObjectName("progressStatus")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("runProgress")
        self.progress_bar.setRange(0, 0)  # busy until GridPACK reports a total
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        self.progress_group.setVisible(False)

        self.log = QTextEdit()
        self.log.setObjectName("logPane")
        self.log.setReadOnly(True)
        self.log.setToolTip("Live GridPACK run output.")

        layout.addWidget(self.project_label)
        layout.addWidget(config_box)
        layout.addLayout(action_row)
        layout.addWidget(self.progress_group)
        log_label = QLabel("Run log")
        log_label.setObjectName("sectionTitle")
        layout.addWidget(log_label)
        layout.addWidget(self.log, stretch=1)

    def set_project(self, project: Project, project_data: ProjectData) -> None:
        self.project = project
        self.project_data = project_data
        if project_data.xml_file_name:
            self.project_label.setText(f"Ready: {project_data.name} ({project.root_dir})")
            self.run_button.setEnabled(True)
        else:
            self.project_label.setText(f"Configuration needed: {project_data.name} ({project.root_dir})")
            self.run_button.setEnabled(False)

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
        if not self.project_data.xml_file_name:
            QMessageBox.warning(self, "No XML configuration", "Generate an XML configuration before running.")
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
        self.terminate_button.setEnabled(True)
        self.open_run_button.setEnabled(False)
        self.active_request = request
        self.termination_requested = False
        self._begin_progress()

        self.worker = RunWorker(request)
        self.worker.log_line.connect(self.append_log)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_run.connect(self.on_finished)
        self.worker.failed_run.connect(self.on_failed)
        self.worker.start()

    def append_log(self, text: str) -> None:
        self.log.append(text.rstrip())

    def _begin_progress(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting Docker run...")
        self.progress_group.setVisible(True)

    def on_progress(self, update: object) -> None:
        from gridlens.runner.run_progress import RunProgress

        if not isinstance(update, RunProgress):
            return
        self.progress_label.setText(update.message)
        if update.total:
            self.progress_bar.setRange(0, update.total)
            self.progress_bar.setValue(min(update.completed, update.total))
        else:
            # Total not yet known: keep the indeterminate busy animation.
            self.progress_bar.setRange(0, 0)

    def _finalize_progress(self, message: str, *, complete: bool) -> None:
        self.progress_label.setText(message)
        if complete:
            total = self.progress_bar.maximum()
            if total <= 0:
                self.progress_bar.setRange(0, 1)
                total = 1
            self.progress_bar.setValue(total)

    def terminate_run(self) -> None:
        if not self.active_request:
            QMessageBox.warning(self, "No active run", "There is no active GridPACK run to terminate.")
            return
        if self.terminate_worker and self.terminate_worker.isRunning():
            return

        response = QMessageBox.question(
            self,
            "Terminate run",
            "Terminate the active GridPACK Docker run?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return

        self.termination_requested = True
        self.terminate_button.setEnabled(False)
        self.append_log(f"Terminating Docker container: {self.active_request.container_name}")

        self.terminate_worker = TerminateWorker(self.active_request.container_name)
        self.terminate_worker.finished_terminate.connect(self.on_terminated)
        self.terminate_worker.failed_terminate.connect(self.on_terminate_failed)
        self.terminate_worker.start()

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
        self.terminate_button.setEnabled(False)
        self.last_run_dir = result.run_dir
        self.open_run_button.setEnabled(True)
        if self.termination_requested:
            self._finalize_progress("Run terminated.", complete=False)
            self.append_log(f"Run terminated with return code {result.return_code}.")
            QMessageBox.information(self, "Run terminated", "The GridPACK Docker run was terminated.")
        elif result.return_code == 0:
            self._finalize_progress("Run completed successfully.", complete=True)
            self.append_log("Run completed successfully.")
            QMessageBox.information(self, "Run completed", "GridPACK completed successfully.")
        else:
            self._finalize_progress(f"Run failed with return code {result.return_code}.", complete=False)
            self.append_log(f"Run failed with return code {result.return_code}.")
            QMessageBox.warning(self, "Run failed", f"GridPACK exited with return code {result.return_code}.")
        self.active_request = None
        self.termination_requested = False
        self.run_finished.emit(result.run_dir)

    def on_failed(self, error_text: str) -> None:
        self.run_button.setEnabled(True)
        self.terminate_button.setEnabled(False)
        self.active_request = None
        self.termination_requested = False
        self._finalize_progress("Run error.", complete=False)
        self.append_log(error_text)
        QMessageBox.critical(self, "Run error", error_text)

    def on_terminated(self, result: GridpackTerminationResult) -> None:
        self.append_log(result.message)
        if result.stopped or result.killed:
            QMessageBox.information(self, "Terminate requested", result.message)
        else:
            self.terminate_button.setEnabled(self.worker is not None and self.worker.isRunning())
            QMessageBox.warning(self, "Terminate failed", result.message)

    def on_terminate_failed(self, error_text: str) -> None:
        self.terminate_button.setEnabled(self.worker is not None and self.worker.isRunning())
        self.append_log(error_text)
        QMessageBox.critical(self, "Terminate error", error_text)

    def open_last_run(self) -> None:
        if self.last_run_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_run_dir)))
