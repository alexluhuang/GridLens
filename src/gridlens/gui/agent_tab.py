from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from gridlens.agent.controller import AgentController, MAX_PROMPT_CHARS, normalize_citations, session_sources
from gridlens.agent.hermes import DEFAULT_ENDPOINT, HermesAdapter
from gridlens.agent.policy import AgentError
from gridlens.agent.runtime import RuntimeEvent, RuntimeStatus
from gridlens.agent.session import SessionContext, export_session, scoped_path
from gridlens.core.project import Project
from gridlens.analysis.csv_flat import CSV_FLAT_ALLOW_CPU_DASK_ENV, cpu_dask_fallback_warning
from gridlens.gui.agent_jobs import AgentAnalysisWorker
from gridlens.gui.results_view_models import read_run_status
from gridlens.gui.theme import set_button_role, set_context_label


class RuntimeProbe(QThread):
    probed = Signal(object)

    def __init__(self, endpoint: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.endpoint = endpoint

    def run(self) -> None:
        self.probed.emit(HermesAdapter(self.endpoint).probe())


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self.project_label = QLabel("Open a project and select a completed run.")
        self.project_label.setTextFormat(Qt.PlainText)
        set_context_label(self.project_label)
        layout.addWidget(self.project_label)
        form = QFormLayout()
        self.runtime_combo = QComboBox()
        self.runtime_combo.addItems(["Hermes + local Ollama", "Codex (hosted, unavailable)", "Claude Code (hosted, unavailable)"])
        for index in (1, 2):
            self.runtime_combo.model().item(index).setEnabled(False)
            self.runtime_combo.setItemData(index, "Hosted inference is disabled by the repository's local-only CEII policy.", Qt.ToolTipRole)
        form.addRow("Runtime", self.runtime_combo)
        endpoint_row = QHBoxLayout()
        self.endpoint = QLineEdit(DEFAULT_ENDPOINT)
        self.endpoint.setToolTip("Local Ollama endpoint. Authentication is not required for local Ollama.")
        self.refresh_button = QPushButton("Check runtime")
        self.refresh_button.clicked.connect(self.check_runtime)
        endpoint_row.addWidget(self.endpoint, 1)
        endpoint_row.addWidget(self.refresh_button)
        form.addRow("Ollama URL", endpoint_row)
        self.model_combo = QComboBox()
        form.addRow("Local model", self.model_combo)
        self.run_combo = QComboBox()
        self.compare_combo = QComboBox()
        self.compare_combo.addItem("No comparison", "")
        form.addRow("Completed run", self.run_combo)
        form.addRow("Compare with", self.compare_combo)
        layout.addLayout(form)
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
        setup = QLabel(
            'Setup: <a href="https://hermes-agent.nousresearch.com/docs/getting-started/installation/">Hermes installation</a>'
            ' · <a href="https://docs.ollama.com/quickstart">Ollama setup</a>'
            '<br>Terminal checks: <code>hermes --version</code> · <code>ollama serve</code> · <code>ollama list</code>'
            '<br>Install models yourself with <code>ollama pull MODEL</code>. GridLens supplies no inference or model installer.'
        )
        setup.setOpenExternalLinks(True)
        setup.setWordWrap(True)
        setup.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(setup)

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
        self.endpoint.textEdited.connect(self.endpoint_changed)
        self.update_controls()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._probed_once:
            self._probed_once = True
            self.check_runtime()

    def set_project(self, project: Project) -> None:
        if self.project is not None and self.project.root_dir == project.root_dir:
            self.refresh_runs()
            return
        self.project = project
        self.project_label.setText(f"Project: {project.name} ({project.root_dir})")
        self.refresh_runs()
        self.new_session()
        self.refresh_history()

    def refresh_runs(self, select_run: Path | None = None) -> None:
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
        if self.project and Path(str(run_dir)).parent.resolve() == self.project.runs_dir.resolve():
            self.refresh_runs(Path(str(run_dir)))

    def endpoint_changed(self) -> None:
        self.runtime_status = None
        self.new_session()
        self.diagnostics.setText("Endpoint changed. Check runtime before sending.")

    def check_runtime(self) -> None:
        if self.probe_worker is not None or self.worker is not None or self.analysis_worker is not None:
            return
        self.diagnostics.setText("Checking Hermes and local Ollama…")
        self.probe_worker = RuntimeProbe(self.endpoint.text(), self)
        self.probe_worker.probed.connect(self.on_probed)
        self.probe_worker.finished.connect(self.probe_finished)
        self.probe_worker.start()
        self.update_controls()

    def on_probed(self, status: RuntimeStatus) -> None:
        self.runtime_status = status
        self.diagnostics.setText(status.message)
        selected = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(status.models)
        index = self.model_combo.findText(selected)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)
        if selected != self.model_combo.currentText():
            self.new_session()
        self.update_controls()

    def probe_finished(self) -> None:
        worker = self.probe_worker
        self.probe_worker = None
        if worker:
            worker.deleteLater()
        self.update_controls()

    def new_session(self, *_args) -> None:
        if self.controller:
            self.controller.cancel()
        self.controller = None
        self.session_directory = None
        self._history_view = False
        self._parts = []
        self.transcript.clear()
        self.activity.clear()
        self.sources.clear()
        self.history_combo.setCurrentIndex(0)
        self.update_controls()

    def send(self) -> None:
        if not self.send_button.isEnabled() or not self.project:
            return
        prompt = self.input.toPlainText().strip()
        try:
            if self.controller is None or self.controller.cancelled.is_set():
                run_ids = (self.run_combo.currentData(),)
                comparison = self.compare_combo.currentData()
                if comparison and comparison != run_ids[0]:
                    run_ids += (comparison,)
                context = SessionContext.create(self.project.root_dir, run_ids, self.model_combo.currentText(), self.runtime_status.endpoint)
                self.controller = AgentController(context, HermesAdapter(context.endpoint))
                self.session_directory = context.directory
            self.controller.cancelled.clear()
            self._parts.append("You\n" + prompt)
            self.transcript.setPlainText("\n\n".join(self._parts))
            self.input.clear()
            self.worker = AgentWorker(self.controller, prompt, self)
            self.worker.event_received.connect(self.on_event)
            self.worker.answered.connect(self.on_answer)
            self.worker.finished.connect(self.turn_finished)
            self.worker.start()
            self.activity.appendPlainText("Starting local analysis…")
            self.update_controls()
        except (AgentError, OSError) as exc:
            self.diagnostics.setText(str(exc))

    def on_event(self, event: RuntimeEvent) -> None:
        if not self.worker or self.worker.controller is not self.controller:
            return
        if event.kind in ("tool_start", "tool_result", "session"):
            self.activity.appendPlainText(f"{event.kind}: {event.text or 'Hermes session started'}")
        elif event.kind == "error":
            self.activity.appendPlainText(event.text)
            self._parts.append("Agent\n" + event.text)
            self.transcript.setPlainText("\n\n".join(self._parts))
        self.update_sources()

    def on_answer(self, answer: str) -> None:
        if not self.worker or self.worker.controller is not self.controller or not self.session_directory:
            return
        sources = session_sources(self.session_directory)
        self._parts.append("Agent\n" + cited_answer(answer, sources))
        self.transcript.setPlainText("\n\n".join(self._parts))
        self.update_sources()

    def update_sources(self) -> None:
        if not self.session_directory:
            return
        blocks = []
        for event in session_sources(self.session_directory):
            result = event["result"]
            data = result["data"]
            paths = "\n".join(source["path"] for source in result["provenance"]["sources"])
            blocks.append(f"[{event['call_id']}] {event['tool']} ({event['outcome']})\n{data['returned']} of {data['total_matching']} rows; truncated: {data['truncated']}\n{paths}")
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
        busy = self.worker is not None or self.analysis_worker is not None
        probing = self.probe_worker is not None
        for control in (self.endpoint, self.refresh_button, self.model_combo, self.run_combo, self.compare_combo, self.history_combo):
            control.setEnabled(not busy and not probing)
        self.stop_button.setEnabled(busy)
        self.build_button.setEnabled(bool(not busy and not probing and self.project and self.run_combo.currentData()))
        self.index_checkbox.setEnabled(not busy)
        prompt = self.input.toPlainText().strip()
        ready = self.runtime_status is not None and self.runtime_status.ready
        self.send_button.setEnabled(bool(not busy and not probing and not self._history_view and ready and self.project and self.run_combo.currentData() and prompt and len(prompt) <= MAX_PROMPT_CHARS))
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
                self.diagnostics.setText("Session audit exported. It contains project-derived data and conversation text.")
            except (AgentError, OSError) as exc:
                self.diagnostics.setText(str(exc))

    def review_scripts(self) -> None:
        if not self.session_directory:
            return
        from gridlens.gui.script_review import ScriptReview

        try:
            context = SessionContext.load(self.session_directory / "context.json")
            dialog = ScriptReview(context, self)
            dialog.exec()
        except (AgentError, OSError) as exc:
            self.diagnostics.setText(str(exc))

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
            self.analysis_worker.outcome.connect(self.diagnostics.setText)
            self.analysis_worker.finished.connect(self.analysis_finished)
            self.analysis_worker.start()
            self.update_controls()
        except (AgentError, OSError) as exc:
            self.diagnostics.setText(str(exc))

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
            self.diagnostics.setText("The project session folder is not a regular directory.")

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
