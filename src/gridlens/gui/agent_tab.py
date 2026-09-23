from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from gridlens.agent.controller import AgentController, MAX_PROMPT_CHARS, normalize_citations, session_sources
from gridlens.agent.hermes import DEFAULT_ENDPOINT
from gridlens.agent.policy import AgentError
from gridlens.agent.providers import DESCRIPTORS, create_adapter, descriptor
from gridlens.agent.runtime import RuntimeEvent, RuntimeStatus
from gridlens.agent.session import SessionContext, export_session, scoped_path
from gridlens.agent.tools import TOOL_NAMES
from gridlens.core.project import Project
from gridlens.analysis.csv_flat import CSV_FLAT_ALLOW_CPU_DASK_ENV, cpu_dask_fallback_warning
from gridlens.gui.agent_jobs import AgentAnalysisWorker
from gridlens.gui.results_view_models import read_run_status
from gridlens.gui.theme import set_button_role, set_context_label


class RuntimeProbe(QThread):
    probed = Signal(object)

    def __init__(self, provider: str, endpoint: str, parent: QWidget) -> None:
        """Probe the selected provider and endpoint on a worker thread; emit its status to AgentTab."""
        super().__init__(parent)
        self.provider = provider
        self.endpoint = endpoint

    def run(self) -> None:
        """Return an adapter status without blocking the GUI thread."""
        try:
            self.probed.emit(create_adapter(self.provider, self.endpoint).probe())
        except (AgentError, OSError) as exc:
            self.probed.emit(RuntimeStatus(False, str(exc), provider=self.provider, route=descriptor(self.provider).route))


class AgentWorker(QThread):
    event_received = Signal(object)
    answered = Signal(str)

    def __init__(self, controller: AgentController, prompt: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.controller = controller
        self.prompt = prompt

    def run(self) -> None:
        try:
            self.answered.emit(self.controller.run_turn(self.prompt, self.event_received.emit))
        except AgentError:
            pass  # The controller already emitted and audited the error.


def cited_answer(text: str, sources: list[dict]) -> str:
    return normalize_citations(text, sources)


class AgentTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.controller: AgentController | None = None
        self.worker: AgentWorker | None = None
        self.probe_worker: RuntimeProbe | None = None
        self.analysis_worker: AgentAnalysisWorker | None = None
        self.runtime_status: RuntimeStatus | None = None
        self.session_directory: Path | None = None
        self._probed_once = False
        self._history_view = False
        self._parts: list[str] = []
        self._streaming = False
        self._streamed_chars = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self.project_label = QLabel("Open a project and select a completed run.")
        self.project_label.setTextFormat(Qt.PlainText)
        set_context_label(self.project_label)
        layout.addWidget(self.project_label)
        form = QFormLayout()
        self.runtime_combo = QComboBox()
        for item in DESCRIPTORS:
            self.runtime_combo.addItem(item.label, item.provider)
        runtime_row = QHBoxLayout()
        runtime_row.addWidget(self.runtime_combo, 1)
        self.route_badge = QLabel("Local (unverified)")
        self.route_badge.setTextFormat(Qt.PlainText)
        runtime_row.addWidget(self.route_badge)
        form.addRow("Runtime", runtime_row)
        self.endpoint_container = QWidget()
        endpoint_row = QHBoxLayout(self.endpoint_container)
        endpoint_row.setContentsMargins(0, 0, 0, 0)
        self.endpoint = QLineEdit(DEFAULT_ENDPOINT)
        self.endpoint.setToolTip("Local Ollama endpoint. Authentication is not required for local Ollama.")
        self.refresh_button = QPushButton("Check runtime")
        self.refresh_button.clicked.connect(self.check_runtime)
        endpoint_row.addWidget(self.endpoint, 1)
        endpoint_row.addWidget(self.refresh_button)
        self.endpoint_label = QLabel("Ollama URL")
        form.addRow(self.endpoint_label, self.endpoint_container)
        self.model_combo = QComboBox()
        self.model_label = QLabel("Local model")
        form.addRow(self.model_label, self.model_combo)
        self.run_combo = QComboBox()
        self.compare_combo = QComboBox()
        self.compare_combo.addItem("No comparison", "")
        form.addRow("Completed run", self.run_combo)
        form.addRow("Compare with", self.compare_combo)
        layout.addLayout(form)
        self.runtime_policy = QLabel(
            "Hosted runtimes send questions and tool results online. The local-only CEII policy in "
            "CONTRIBUTING.md and docs/security_ceii.md keeps them unavailable until a separate authorization."
        )
        self.runtime_policy.setTextFormat(Qt.PlainText)
        self.runtime_policy.setWordWrap(True)
        set_context_label(self.runtime_policy)
        layout.addWidget(self.runtime_policy)
        self.remote_acknowledgement = QCheckBox("I understand this provider sends my questions and project-derived tool results off this machine.")
        layout.addWidget(self.remote_acknowledgement)
        self.tool_scope = QLabel(f"GridLens tools: {len(TOOL_NAMES)}. Runtime isolation is checked before a session starts.")
        self.tool_scope.setTextFormat(Qt.PlainText)
        layout.addWidget(self.tool_scope)
        build_row = QHBoxLayout()
        self.build_button = QPushButton("Build / refresh analysis")
        self.build_button.clicked.connect(self.build_analysis)
        self.index_checkbox = QCheckBox("Include contingency drill-down index")
        self.index_checkbox.setToolTip("Reads the flat results once and stores a Parquet index under reports/. This may take several minutes.")
        build_row.addWidget(self.build_button)
        build_row.addWidget(self.index_checkbox)
        build_row.addStretch(1)
        layout.addLayout(build_row)
        self.diagnostics = QLabel("Local inference only. Select Check runtime to detect Hermes and installed Ollama models.")
        self.diagnostics.setTextFormat(Qt.PlainText)
        self.diagnostics.setWordWrap(True)
        layout.addWidget(self.diagnostics)
        self.setup_message = QLabel()
        self.setup_message.setTextFormat(Qt.PlainText)
        self.setup_message.setWordWrap(True)
        layout.addWidget(self.setup_message)
        setup_row = QHBoxLayout()
        self.setup_command = QLineEdit()
        self.setup_command.setReadOnly(True)
        self.setup_command.setPlaceholderText("Installation and sign-in guidance appears after the runtime check.")
        self.copy_setup_button = QPushButton("Copy command")
        self.copy_setup_button.clicked.connect(lambda: QApplication.clipboard().setText(self.setup_command.text()))
        self.docs_button = QPushButton("Provider documentation")
        self.docs_button.clicked.connect(self.open_provider_docs)
        setup_row.addWidget(self.setup_command, 1)
        setup_row.addWidget(self.copy_setup_button)
        setup_row.addWidget(self.docs_button)
        layout.addLayout(setup_row)

        history_row = QHBoxLayout()
        self.history_combo = QComboBox()
        self.history_combo.addItem("Current conversation", "")
        self.history_combo.activated.connect(self.open_history)
        self.new_button = QPushButton("New conversation")
        self.new_button.clicked.connect(self.new_session)
        self.folder_button = QPushButton("Open session folder")
        self.folder_button.clicked.connect(self.open_session_folder)
        self.export_button = QPushButton("Export session audit")
        self.export_button.clicked.connect(self.export_audit)
        self.review_button = QPushButton("Review scripts")
        self.review_button.clicked.connect(self.review_scripts)
        history_row.addWidget(self.history_combo, 1)
        history_row.addWidget(self.new_button)
        history_row.addWidget(self.folder_button)
        history_row.addWidget(self.export_button)
        history_row.addWidget(self.review_button)
        layout.addLayout(history_row)

        split = QSplitter(Qt.Horizontal)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Ask about congestion, thermal margin, convergence, study settings, or run files.")
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Activity"))
        self.activity = QPlainTextEdit()
        self.activity.setReadOnly(True)
        self.activity.setMaximumBlockCount(500)
        right_layout.addWidget(self.activity, 1)
        right_layout.addWidget(QLabel("Sources"))
        self.sources = QPlainTextEdit()
        self.sources.setReadOnly(True)
        right_layout.addWidget(self.sources, 2)
        split.addWidget(self.transcript)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Where are the most congested lines in this run?")
        self.input.setMaximumHeight(95)
        self.input.textChanged.connect(self.update_controls)
        layout.addWidget(self.input)
        buttons = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.stop_button = QPushButton("Stop")
        set_button_role(self.send_button, "primary")
        self.send_button.clicked.connect(self.send)
        self.stop_button.clicked.connect(self.stop)
        buttons.addStretch(1)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        for combo in (self.model_combo, self.run_combo, self.compare_combo):
            combo.currentIndexChanged.connect(self.new_session)
        self.model_combo.editTextChanged.connect(self.new_session)
        self.runtime_combo.currentIndexChanged.connect(self.provider_changed)
        self.remote_acknowledgement.toggled.connect(self.update_controls)
        self.endpoint.textEdited.connect(self.endpoint_changed)
        self.provider_changed(probe=False)
        self.update_controls()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._probed_once:
            self._probed_once = True
            self.check_runtime()

    def set_project(self, project: Project) -> None:
        """Show a project and its runs when neither worker holds the current session."""
        if not self._can_retarget():
            return
        if self.project is not None and self.project.root_dir == project.root_dir:
            self.refresh_runs()
            return
        self.project = project
        self.project_label.setText(f"Project: {project.name} ({project.root_dir})")
        self.refresh_runs()
        self.new_session()
        self.refresh_history()

    def refresh_runs(self, select_run: Path | None = None) -> None:
        """Refresh completed run choices without changing an active turn's scope."""
        if not self._can_retarget():
            return
        previous = self.run_combo.currentData()
        comparison = self.compare_combo.currentData()
        for combo in (self.run_combo, self.compare_combo):
            combo.blockSignals(True)
            combo.clear()
        self.compare_combo.addItem("No comparison", "")
        if self.project:
            for path in self.project.list_runs():
                if not path.is_symlink() and read_run_status(path) == "completed":
                    self.run_combo.addItem(path.name, path.name)
                    self.compare_combo.addItem(path.name, path.name)
        desired = select_run.name if select_run else previous
        index = self.run_combo.findData(desired)
        if index >= 0:
            self.run_combo.setCurrentIndex(index)
        self.compare_combo.setCurrentIndex(max(0, self.compare_combo.findData(comparison)))
        for combo in (self.run_combo, self.compare_combo):
            combo.blockSignals(False)
        if previous != self.run_combo.currentData():
            self.new_session()
        self.update_controls()

    def select_run(self, run_dir: object) -> None:
        """Select an external run signal only when it belongs to the open project."""
        if self.project and Path(str(run_dir)).parent.resolve() == self.project.runs_dir.resolve():
            self.refresh_runs(Path(str(run_dir)))

    def _can_retarget(self) -> bool:
        """Return whether a new project or run can replace the current session."""
        return self.worker is None and self.analysis_worker is None

    def provider_changed(self, *_args, probe: bool = True) -> None:
        """Apply provider-specific fields, clear the old session, and probe the selected CLI."""
        item = descriptor(self.runtime_combo.currentData())
        self.runtime_status = None
        self.remote_acknowledgement.setChecked(False)
        self.remote_acknowledgement.setVisible(not item.local)
        self.endpoint_container.setVisible(item.needs_endpoint)
        self.endpoint_label.setVisible(item.needs_endpoint)
        self.model_label.setText("Local model" if item.enumerates_models else "Model (default = CLI default)")
        self.model_combo.setEditable(not item.enumerates_models)
        self.model_combo.clear()
        if not item.enumerates_models:
            self.model_combo.addItem("default")
        self.route_badge.setText("Local (unverified)" if item.local else "Remote")
        self.setup_message.setText("Select Check runtime to detect the CLI and sign-in state.")
        self.setup_command.clear()
        self.docs_button.setEnabled(False)
        self.new_session()
        if probe:
            self.check_runtime()

    def endpoint_changed(self) -> None:
        """Invalidate the verified local route when its endpoint changes."""
        self.runtime_status = None
        self.new_session()
        self.diagnostics.setText("Endpoint changed. Check runtime before sending.")
        self.route_badge.setText("Local (unverified)")

    def check_runtime(self) -> None:
        """Probe the selected CLI in a worker, without sending a project prompt."""
        if self.probe_worker is not None or self.worker is not None or self.analysis_worker is not None:
            return
        provider = self.runtime_combo.currentData()
        self.diagnostics.setText(f"Checking {descriptor(provider).label}…")
        self.probe_worker = RuntimeProbe(provider, self.endpoint.text() if descriptor(provider).needs_endpoint else "", self)
        self.probe_worker.probed.connect(self.on_probed)
        self.probe_worker.finished.connect(self.probe_finished)
        self.probe_worker.start()
        self.update_controls()

    def on_probed(self, status: RuntimeStatus) -> None:
        """Render the selected CLI's installation, sign-in, route, and model status."""
        if status.provider != self.runtime_combo.currentData():
            return
        self.runtime_status = status
        self.diagnostics.setText(status.message)
        self.route_badge.setText("Remote" if status.remote else "Local (loopback)" if status.endpoint else "Local (unverified)")
        if not status.installed:
            self.setup_message.setText("Install this CLI yourself using its provider documentation, then check runtime again.")
            command = status.install_command if status.remote else ""
        elif status.authenticated is False:
            self.setup_message.setText("Sign in through the CLI using your own credentials, then check runtime again.")
            command = status.login_command
        elif status.policy_blocked:
            self.setup_message.setText("This runtime is detected but cannot send project data under the current CEII policy or isolation gate.")
            command = ""
        elif not status.ready and not status.remote and not status.models:
            self.setup_message.setText("Install a tool-capable local Ollama model yourself, then check runtime again.")
            command = status.install_command
        else:
            self.setup_message.setText("Runtime ready. GridLens supplies no inference, model installer, or credentials.")
            command = ""
        self.setup_command.setText(command)
        self.docs_button.setEnabled(bool(status.docs_url))
        selected = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(status.models if descriptor(status.provider).enumerates_models else (selected or "default",))
        index = self.model_combo.findText(selected)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)
        if selected != self.model_combo.currentText():
            self.new_session()
        self.update_controls()

    def open_provider_docs(self) -> None:
        """Open the selected provider's documented setup page without starting an installer."""
        if self.runtime_status and self.runtime_status.docs_url:
            QDesktopServices.openUrl(QUrl(self.runtime_status.docs_url))

    def probe_finished(self) -> None:
        worker = self.probe_worker
        self.probe_worker = None
        if worker:
            worker.deleteLater()
        self.update_controls()

    def new_session(self, *_args) -> None:
        """Clear the current conversation after a scope or model change."""
        if self.controller:
            self.controller.cancel()
        self.controller = None
        self.session_directory = None
        self._history_view = False
        self._parts = []
        self._streaming = False
        self._streamed_chars = 0
        self.transcript.clear()
        self.activity.clear()
        self.sources.clear()
        self.history_combo.setCurrentIndex(0)
        self.update_controls()

    def send(self) -> None:
        """Create a scoped session and launch one model turn for the user's prompt."""
        if not self.send_button.isEnabled() or not self.project:
            return
        prompt = self.input.toPlainText().strip()
        try:
            if self.controller is None or self.controller.cancelled.is_set():
                run_ids = (self.run_combo.currentData(),)
                comparison = self.compare_combo.currentData()
                if comparison and comparison != run_ids[0]:
                    run_ids += (comparison,)
                context = SessionContext.create(
                    self.project.root_dir, run_ids, self.model_combo.currentText(), self.runtime_status.endpoint,
                    runtime=self.runtime_combo.currentData(), remote_acknowledged=self.remote_acknowledgement.isChecked(),
                )
                self.controller = AgentController(context, create_adapter(context.runtime, context.endpoint))
                self.session_directory = context.directory
            self.controller.cancelled.clear()
            self._streaming = False
            self._streamed_chars = 0
            self._parts.append("You\n" + prompt)
            self.transcript.setPlainText("\n\n".join(self._parts))
            self.input.clear()
            self.worker = AgentWorker(self.controller, prompt, self)
            self.worker.event_received.connect(self.on_event)
            self.worker.answered.connect(self.on_answer)
            self.worker.finished.connect(self.turn_finished)
            self.worker.start()
            self.activity.appendPlainText("Starting agent turn…")
            self.update_controls()
        except (AgentError, OSError) as exc:
            self.activity.appendPlainText(str(exc))

    def on_event(self, event: RuntimeEvent) -> None:
        """Render a normalized runtime event and refresh sources only after a tool result."""
        if not self.worker or self.worker.controller is not self.controller:
            return
        if event.kind in ("tool_start", "tool_result", "session"):
            self.activity.appendPlainText(f"{event.kind}: {event.text or 'Agent session started'}")
            if event.kind == "tool_result":
                self.update_sources()
        elif event.kind == "text":
            if not self._streaming:
                self.transcript.appendPlainText("\nAgent\n")
                self._streaming = True
            remaining = max(0, 256_000 - self._streamed_chars)
            delta = event.text[:remaining]
            self.transcript.moveCursor(QTextCursor.End)
            self.transcript.insertPlainText(delta)
            self._streamed_chars += len(delta)
            if len(delta) < len(event.text) and remaining:
                self.transcript.insertPlainText("\n[Output truncated in view; see runtime_events.jsonl.]")
        elif event.kind == "error":
            self.activity.appendPlainText(event.text)
            self._streaming = False
            self._parts.append("Agent\n" + event.text)
            self.transcript.setPlainText("\n\n".join(self._parts))

    def on_answer(self, answer: str) -> None:
        """Replace streamed text with the canonical answer after validating its citations."""
        if not self.worker or self.worker.controller is not self.controller or not self.session_directory:
            return
        sources = session_sources(self.session_directory)
        self._streaming = False
        self._parts.append("Agent\n" + cited_answer(answer, sources))
        self.transcript.setPlainText("\n\n".join(self._parts))
        self.update_sources()

    def update_sources(self) -> None:
        """Show audited tool results, including errors, warnings, filters, and relative sources."""
        if not self.session_directory:
            return
        blocks = []
        for event in session_sources(self.session_directory):
            result = event.get("result") or {}
            data = result.get("data") or {}
            error = result.get("error") or {}
            lines = [f"[{event.get('call_id', '?')}] {event.get('tool', '?')} ({event.get('outcome', '?')})"]
            if error:
                lines.append(f"error {str(error.get('code', 'UNKNOWN'))[:64]}: {str(error.get('remedy', ''))[:300]}")
            else:
                lines.append(f"{data.get('returned', 0)} of {data.get('total_matching', 0)} rows; truncated: {data.get('truncated', False)}")
            if data.get("limit") is not None:
                lines.append(f"offset: {data.get('offset') or 0}; limit: {'all rows' if data['limit'] == 0 else data['limit']}")
            if data.get("result_file"):
                lines.append(f"complete result: {data.get('rows_file') or data['result_file']} ({data.get('inline_rows', 0)} rows shown inline)")
            if data.get("analyzed_facility_count") is not None:
                lines.append(f"matching facilities used: {data['analyzed_facility_count']}")
            if data.get("filters"):
                lines.append(f"filters: {str(data['filters'])[:300]}")
            lines.extend(f"warning: {str(warning)[:300]}" for warning in (result.get("warnings") or [])[:10])
            lines.extend(str(source.get("path", ""))[:300] for source in ((result.get("provenance") or {}).get("sources") or []))
            blocks.append("\n".join(lines))
        self.sources.setPlainText("\n\n".join(blocks))

    def turn_finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self.refresh_history()
        self.update_controls()

    def stop(self) -> None:
        if self.analysis_worker:
            self.analysis_worker.cancelled.set()
            self.activity.appendPlainText("Stopping analysis…")
        if self.worker:
            self.worker.controller.cancel()
            self.activity.appendPlainText("Stopping…")

    def update_controls(self) -> None:
        """Enable actions only when the selected session scope and runtime are ready."""
        busy = self.worker is not None or self.analysis_worker is not None
        probing = self.probe_worker is not None
        for control in (self.runtime_combo, self.endpoint, self.refresh_button, self.model_combo, self.run_combo, self.compare_combo, self.history_combo, self.new_button):
            control.setEnabled(not busy and not probing)
        self.remote_acknowledgement.setEnabled(not busy and not probing)
        self.copy_setup_button.setEnabled(bool(self.setup_command.text()))
        self.stop_button.setEnabled(busy)
        self.build_button.setEnabled(bool(not busy and not probing and self.project and self.run_combo.currentData()))
        self.index_checkbox.setEnabled(not busy)
        prompt = self.input.toPlainText().strip()
        ready = self.runtime_status is not None and self.runtime_status.ready and self.runtime_status.provider == self.runtime_combo.currentData()
        acknowledged = not descriptor(self.runtime_combo.currentData()).route == "remote" or self.remote_acknowledgement.isChecked()
        self.send_button.setEnabled(bool(not busy and not probing and not self._history_view and ready and acknowledged and self.model_combo.currentText().strip() and self.project and self.run_combo.currentData() and prompt and len(prompt) <= MAX_PROMPT_CHARS))
        self.folder_button.setEnabled(self.session_directory is not None)
        self.export_button.setEnabled(not busy and self.session_directory is not None)
        self.review_button.setEnabled(not busy and self.session_directory is not None)

    def export_audit(self) -> None:
        if not self.session_directory:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Export sensitive session audit", str(self.session_directory.parent / (self.session_directory.name + ".zip")), "ZIP archive (*.zip)")
        if destination:
            try:
                export_session(self.session_directory, Path(destination))
                self.activity.appendPlainText("Session audit exported. It contains project-derived data and conversation text.")
            except (AgentError, OSError) as exc:
                self.activity.appendPlainText(str(exc))

    def review_scripts(self) -> None:
        if not self.session_directory:
            return
        from gridlens.gui.script_review import ScriptReview

        try:
            context = SessionContext.load(self.session_directory / "context.json")
            dialog = ScriptReview(context, self)
            dialog.exec()
        except (AgentError, OSError) as exc:
            self.activity.appendPlainText(str(exc))

    def build_analysis(self) -> None:
        if not self.build_button.isEnabled() or not self.project:
            return
        try:
            run_ids = dict.fromkeys(value for value in (self.run_combo.currentData(), self.compare_combo.currentData()) if value)
            runs = [scoped_path(self.project.root_dir, Path("runs") / run_id, directory=True) for run_id in run_ids]
            warning = next((text for run in runs if (text := cpu_dask_fallback_warning(run))), "")
            if warning:
                QMessageBox.warning(self, "CPU Dask fallback", warning)
                os.environ[CSV_FLAT_ALLOW_CPU_DASK_ENV] = "1"
            self.analysis_worker = AgentAnalysisWorker(runs, self.index_checkbox.isChecked(), self)
            self.analysis_worker.progress.connect(self.activity.appendPlainText)
            self.analysis_worker.outcome.connect(self.activity.appendPlainText)
            self.analysis_worker.finished.connect(self.analysis_finished)
            self.analysis_worker.start()
            self.update_controls()
        except (AgentError, OSError) as exc:
            self.activity.appendPlainText(str(exc))

    def analysis_finished(self) -> None:
        worker = self.analysis_worker
        self.analysis_worker = None
        if worker:
            worker.deleteLater()
        self.update_controls()

    def refresh_history(self) -> None:
        self.history_combo.clear()
        self.history_combo.addItem("Current conversation", "")
        if not self.project:
            return
        try:
            root = scoped_path(self.project.root_dir, "agent/sessions", directory=True)
            for path in sorted(root.iterdir(), reverse=True)[:100] if root.exists() else []:
                if path.is_dir() and not path.is_symlink():
                    self.history_combo.addItem(path.name, str(path))
        except AgentError:
            self.activity.appendPlainText("The project session folder is not a regular directory.")

    def open_history(self, index: int) -> None:
        directory = self.history_combo.itemData(index)
        if not directory:
            self.new_session()
            return
        self.new_session()
        self._history_view = True
        self.session_directory = Path(directory)
        try:
            path = scoped_path(self.session_directory, "transcript.jsonl")
            if path.stat().st_size > 8 * 1024 * 1024:
                raise AgentError("SESSION_LIMIT", "Open the session folder to inspect this large transcript.")
            messages = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            records = session_sources(self.session_directory)
            self.transcript.setPlainText("\n\n".join(f"{item['role']}\n{cited_answer(item['text'], records)}" for item in messages))
            self.update_sources()
            self.activity.setPlainText("Saved session. Choose New conversation to ask another question.")
            self.history_combo.setCurrentIndex(index)
        except (OSError, ValueError) as exc:
            self.activity.setPlainText(f"Could not load this session: {exc}")
        self.update_controls()

    def open_session_folder(self) -> None:
        if self.session_directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session_directory)))

    def shutdown(self) -> bool:
        self.stop()
        if self.analysis_worker and not self.analysis_worker.wait(5000):
            return False
        if self.worker and not self.worker.wait(12_000):
            return False
        if self.probe_worker and not self.probe_worker.wait(12_000):
            return False
        return True
