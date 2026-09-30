"""The Agent tab: a conversation with Clarke, the planning agent, about GridLens projects, runs, and files.

A conversation can start with or without a project open. The open project, and the run selected in the
Results tab or else the project's newest completed run, are where each turn starts; its tools can reach any
project in the projects folder, create new ones, and start runs and analyses. Opening another project or
selecting another run keeps the conversation and moves the next turn there, and the saved conversations of
every project are listed together. After each turn the tab emits `turn_finished`, so the main window can
refresh the run lists the agent may have changed.

The first time the tab is shown, it checks that Hermes Agent, Ollama, and a model are installed, and opens
the Set up Clarke dialog when something is missing.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from gridlens.agent.accounting import summary as turn_summary, turn_accounting
from gridlens.agent.controller import AgentController, MAX_PROMPT_CHARS, normalize_citations, session_sources
from gridlens.agent.conversation_log import write_conversation_log
from gridlens.agent.document_tools import reference_folder
from gridlens.agent.hermes import DEFAULT_ENDPOINT
from gridlens.agent.policy import AgentError
from gridlens.agent.providers import DESCRIPTORS, create_adapter, descriptor
from gridlens.agent.runtime import RuntimeEvent, RuntimeStatus
from gridlens.agent.session import (
    SessionContext, export_session, migrate_legacy_sessions, saved_sessions, scoped_path, session_title,
)
from gridlens.agent.setup import PREFERRED_MODEL, SetupStatus
from gridlens.core.app_settings import AppSettings
from gridlens.core.project import Project
from gridlens.gui.agent_conversation import AgentPromptEdit, ConversationView, ProcessCard
from gridlens.gui.agent_setup import AgentSetupDialog, SetupProbe
from gridlens.gui.results_view_models import read_run_status
from gridlens.gui.theme import configure_form_layout, set_button_role, set_context_label


CLARKE_DOCS_URL = "https://github.com/alexluhuang/GridLens/blob/main/docs/clarke.md"
# The model list's last entry, which opens the Set up Clarke dialog instead of choosing a model.
MANAGE_MODELS = "__manage_models__"
UNAVAILABLE_SUFFIX = " (under development, currently unavailable)"


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


def proposed_scripts(directory: Path | None) -> int:
    """Count the scripts a session has proposed, which Review proposed scripts lists."""
    if directory is None:
        return 0
    try:
        folder = scoped_path(directory, "generated", directory=True)
    except AgentError:
        return 0
    return len(list(folder.glob("*.json"))) if folder.is_dir() else 0


class AgentTab(QWidget):
    turn_finished = Signal()

    def __init__(self, settings: AppSettings | None = None) -> None:
        """Build the tab. settings supplies the projects folder used when no project is open."""
        super().__init__()
        self.settings = settings or AppSettings.load()
        self.project: Project | None = None
        # A project opened while a turn runs, shown once it ends.
        self._pending_project: Project | None = None
        # The run each turn starts from: the one selected in the Results tab, else the newest completed run.
        self.focus_run = ""
        self.controller: AgentController | None = None
        self.worker: AgentWorker | None = None
        self.probe_worker: RuntimeProbe | None = None
        self.setup_probe: SetupProbe | None = None
        self.runtime_status: RuntimeStatus | None = None
        self.setup_status: SetupStatus | None = None
        self.session_directory: Path | None = None
        self.endpoint = DEFAULT_ENDPOINT
        self._checked_setup = False
        self._model_index = -1
        self._draft_label = None
        self._process_card: ProcessCard | None = None
        self._shown_sources = 0
        self._streamed_chars = 0
        try:
            migrate_legacy_sessions(self.settings.default_projects_dir)
        except (AgentError, OSError):
            pass  # An unmoved session stays where it was and is still listed.

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self.project_label = QLabel()
        self.project_label.setTextFormat(Qt.PlainText)
        set_context_label(self.project_label)
        layout.addWidget(self.project_label)
        self.notice = QFrame()
        self.notice.setObjectName("agentSetupNotice")
        notice_row = QHBoxLayout(self.notice)
        notice_row.setContentsMargins(0, 0, 0, 0)
        self.notice_label = QLabel()
        self.notice_label.setTextFormat(Qt.PlainText)
        self.notice_label.setWordWrap(True)
        self.setup_button = QPushButton("Set up Clarke…")
        set_button_role(self.setup_button, "primary")
        self.setup_button.clicked.connect(self.check_setup)
        notice_row.addWidget(self.notice_label, 1)
        notice_row.addWidget(self.setup_button)
        self.notice.hide()
        layout.addWidget(self.notice)
        settings_header = QHBoxLayout()
        self.settings_toggle = QToolButton()
        self.settings_toggle.setObjectName("agentSettingsToggle")
        self.settings_toggle.setText("Session setup")
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setArrowType(Qt.RightArrow)
        self.settings_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        settings_header.addWidget(self.settings_toggle)
        self.session_summary = QLabel()
        self.session_summary.setTextFormat(Qt.PlainText)
        settings_header.addWidget(self.session_summary, 1)
        layout.addLayout(settings_header)
        self.settings_panel = QFrame()
        self.settings_panel.setObjectName("agentSettingsPanel")
        settings_layout = QVBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.setSpacing(8)
        self.settings_toggle.toggled.connect(self.toggle_settings)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("agentSettingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setMaximumHeight(220)
        self.settings_scroll.setWidget(self.settings_panel)
        self.settings_scroll.hide()
        form = QFormLayout()
        configure_form_layout(form)
        self.runtime_combo = QComboBox()
        for item in DESCRIPTORS:
            self.runtime_combo.addItem(item.label if item.local else item.label + UNAVAILABLE_SUFFIX, item.provider)
            if not item.local:
                # Hosted runtimes stay listed so users know they are coming, but cannot be chosen yet.
                self.runtime_combo.model().item(self.runtime_combo.count() - 1).setEnabled(False)
        form.addRow("Runtime", self.runtime_combo)
        self.model_combo = QComboBox()
        self.model_label = QLabel("Local model")
        form.addRow(self.model_label, self.model_combo)
        settings_layout.addLayout(form)
        self.remote_acknowledgement = QCheckBox("I understand this provider sends my questions and project-derived tool results off this machine.")
        settings_layout.addWidget(self.remote_acknowledgement)
        self.docs_link = QLabel(f'To learn more about Clarke, read <a href="{CLARKE_DOCS_URL}">here</a>.')
        self.docs_link.setTextFormat(Qt.RichText)
        self.docs_link.setOpenExternalLinks(True)
        settings_layout.addWidget(self.docs_link)
        session_actions = QHBoxLayout()
        self.folder_button = QPushButton("Open session folder")
        self.folder_button.setToolTip("Open this conversation's folder: conversation.md is the full record of it.")
        self.folder_button.clicked.connect(self.open_session_folder)
        self.export_button = QPushButton("Export session (ZIP)…")
        self.export_button.setToolTip("Save this conversation, its tool calls, and their results as one ZIP file to share or archive.")
        self.export_button.clicked.connect(self.export_audit)
        self.documents_button = QPushButton("Open reference documents")
        self.documents_button.setToolTip("Open the folder of standards, planning criteria, and manuals Clarke can search. Add PDF, text, Markdown, or HTML files to it.")
        self.documents_button.clicked.connect(self.open_reference_documents)
        self.review_button = QPushButton("Review proposed scripts")
        self.review_button.setToolTip("Read, approve, and run the analysis scripts Clarke proposed in this conversation.")
        self.review_button.clicked.connect(self.review_scripts)
        session_actions.addWidget(self.folder_button)
        session_actions.addWidget(self.export_button)
        session_actions.addWidget(self.documents_button)
        session_actions.addWidget(self.review_button)
        session_actions.addStretch(1)
        settings_layout.addLayout(session_actions)
        layout.addWidget(self.settings_scroll)

        history_row = QHBoxLayout()
        self.history_combo = QComboBox()
        self.history_combo.addItem("New conversation", "")
        self.history_combo.activated.connect(self.open_history)
        self.new_button = QPushButton("New conversation")
        self.new_button.clicked.connect(self.new_session)
        history_row.addWidget(self.history_combo, 1)
        history_row.addWidget(self.new_button)
        layout.addLayout(history_row)

        self.conversation = ConversationView()
        layout.addWidget(self.conversation, 1)
        self.audit_toggle = QToolButton()
        self.audit_toggle.setObjectName("agentAuditToggle")
        self.audit_toggle.setText("Full activity and sources")
        self.audit_toggle.setCheckable(True)
        self.audit_toggle.setArrowType(Qt.RightArrow)
        self.audit_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.audit_toggle.toggled.connect(self.toggle_audit)
        layout.addWidget(self.audit_toggle)
        self.audit_panel = QFrame()
        self.audit_panel.setObjectName("agentAuditPanel")
        audit_layout = QHBoxLayout(self.audit_panel)
        activity_column = QVBoxLayout()
        activity_column.addWidget(QLabel("Activity"))
        self.activity = QPlainTextEdit()
        self.activity.setReadOnly(True)
        self.activity.setMaximumBlockCount(500)
        activity_column.addWidget(self.activity)
        sources_column = QVBoxLayout()
        sources_column.addWidget(QLabel("Sources"))
        self.sources = QPlainTextEdit()
        self.sources.setReadOnly(True)
        sources_column.addWidget(self.sources)
        audit_layout.addLayout(activity_column, 2)
        audit_layout.addLayout(sources_column, 3)
        self.audit_panel.setMaximumHeight(220)
        self.audit_panel.hide()
        layout.addWidget(self.audit_panel)
        composer = QHBoxLayout()
        self.input = AgentPromptEdit()
        self.input.setObjectName("agentComposer")
        self.input.setPlaceholderText("Where are the most congested lines in this run?")
        self.input.setMaximumHeight(110)
        self.input.textChanged.connect(self.update_controls)
        self.input.submitted.connect(self.send)
        composer.addWidget(self.input, 1)
        buttons = QVBoxLayout()
        self.send_button = QPushButton("Send")
        self.stop_button = QPushButton("Stop")
        set_button_role(self.send_button, "primary")
        self.send_button.clicked.connect(self.send)
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        composer.addLayout(buttons)
        layout.addLayout(composer)
        self.model_combo.currentIndexChanged.connect(self.model_changed)
        self.model_combo.editTextChanged.connect(self.new_session)
        self.runtime_combo.currentIndexChanged.connect(self.provider_changed)
        self.remote_acknowledgement.toggled.connect(self.update_controls)
        self._show_project_label()
        self.provider_changed(probe=False)
        self.refresh_history()
        self.update_controls()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._checked_setup:
            self._checked_setup = True
            self.check_setup()

    def toggle_settings(self, expanded: bool) -> None:
        """Show setup controls when the user expands Session setup in the Agent tab."""
        if expanded and self.audit_toggle.isChecked():
            self.audit_toggle.setChecked(False)
        self.settings_scroll.setVisible(expanded)
        self.settings_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def toggle_audit(self, expanded: bool) -> None:
        """Show full activity and source text below the conversation when requested."""
        if expanded and self.settings_toggle.isChecked():
            self.settings_toggle.setChecked(False)
        self.audit_panel.setVisible(expanded)
        self.audit_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def set_project(self, project: Project) -> None:
        """Show a project, keeping the conversation; its next turn starts in this project at its newest run.

        While a turn runs, the project is shown once it ends.
        """
        if not self._can_retarget():
            self._pending_project = project
            return
        self._pending_project = None
        if self.project is not None and self.project.root_dir == project.root_dir:
            self.refresh_runs()
            return
        self.project = project
        self.focus_run = ""
        self.refresh_runs()
        self.refresh_history()

    def _show_pending_project(self) -> None:
        """Show the project opened while a turn ran, once the turn has ended."""
        if self._pending_project is not None and self._can_retarget():
            self.set_project(self._pending_project)

    def completed_runs(self) -> list[str]:
        """Return the open project's completed runs, newest first."""
        if not self.project:
            return []
        return [path.name for path in self.project.list_runs() if not path.is_symlink() and read_run_status(path) == "completed"]

    def refresh_runs(self, select_run: Path | None = None) -> None:
        """Keep the focus run, or move it to select_run; fall back to the newest completed run.

        The focus does not change while a turn runs.
        """
        if not self._can_retarget():
            return
        runs = self.completed_runs()
        if select_run is not None and select_run.name in runs:
            self.focus_run = select_run.name
        elif self.focus_run not in runs:
            self.focus_run = runs[0] if runs else ""
        self._show_project_label()
        self.update_controls()

    def select_run(self, run_dir: object) -> None:
        """Follow the run selected in the Results tab when it belongs to the open project."""
        if self.project and Path(str(run_dir)).parent.resolve() == self.project.runs_dir.resolve():
            self.refresh_runs(Path(str(run_dir)))

    def _show_project_label(self) -> None:
        """Say where the next turn starts: the open project and its focus run, or the projects folder."""
        if self.project is None:
            self.project_label.setText("No project is open. Clarke can list, create, and run projects in the projects folder.")
        elif self.focus_run:
            self.project_label.setText(f"Project: {self.project.name} · starting from run {self.focus_run}. Select another run in the Results tab, or name one in your question.")
        else:
            self.project_label.setText(f"Project: {self.project.name} ({self.project.root_dir}). It has no completed run yet.")

    def _can_retarget(self) -> bool:
        """Return whether the project or run shown here can change, which they cannot while a turn runs."""
        return self.worker is None

    def check_setup(self) -> None:
        """Check for Hermes, Ollama, and a model off the GUI thread; the result may open Set up Clarke."""
        if self.setup_probe is not None or self.worker is not None:
            return
        self.notice_label.setText("Checking for Hermes Agent, Ollama, and installed models…")
        self.notice.show()
        self.setup_button.setEnabled(False)
        self.setup_probe = SetupProbe(self)
        self.setup_probe.checked.connect(self.on_setup_checked)
        self.setup_probe.finished.connect(self._setup_probe_finished)
        self.setup_probe.start()

    def _setup_probe_finished(self) -> None:
        worker, self.setup_probe = self.setup_probe, None
        if worker:
            worker.deleteLater()
        self.setup_button.setEnabled(True)

    def on_setup_checked(self, status: SetupStatus) -> None:
        """Open Set up Clarke when something is missing, then check the runtime the tab uses."""
        self.setup_status = status
        if status.started_ollama:
            self.activity.appendPlainText("Ollama was not running, so GridLens started it.")
        if not status.ready:
            self.open_setup(status)
        self.check_runtime()

    def open_setup(self, status: SetupStatus | None = None) -> None:
        """Show Set up Clarke for a checked machine; re-check the runtime once it closes, as it may have changed."""
        status = status or self.setup_status
        if status is None:
            self.check_setup()
            return
        dialog = AgentSetupDialog(status, self)
        dialog.exec()
        self.setup_status = dialog.status
        if dialog.changed:
            self.check_runtime()

    def provider_changed(self, *_args, probe: bool = True) -> None:
        """Apply provider-specific fields, clear the old session, and probe the selected CLI."""
        item = descriptor(self.runtime_combo.currentData())
        self.runtime_status = None
        self.remote_acknowledgement.setChecked(False)
        self.remote_acknowledgement.setVisible(not item.local)
        self.model_label.setText("Local model" if item.enumerates_models else "Model (default = CLI default)")
        self.model_combo.blockSignals(True)
        self.model_combo.setEditable(not item.enumerates_models)
        self.model_combo.clear()
        if not item.enumerates_models:
            self.model_combo.addItem("default", "default")
        self.model_combo.blockSignals(False)
        self._model_index = self.model_combo.currentIndex()
        self.new_session()
        if probe:
            self.check_runtime()

    def selected_model(self) -> str:
        """Return the chosen model name; the model list's manage entry is not a model."""
        if self.model_combo.isEditable():
            return self.model_combo.currentText().strip()
        data = self.model_combo.currentData()
        return "" if data in (None, MANAGE_MODELS) else str(data)

    def model_changed(self, index: int) -> None:
        """Start a new conversation for another model, or open Set up Clarke from the manage entry."""
        if self.model_combo.itemData(index) == MANAGE_MODELS:
            self.model_combo.blockSignals(True)
            self.model_combo.setCurrentIndex(self._model_index)
            self.model_combo.blockSignals(False)
            QTimer.singleShot(0, self.open_setup)
            return
        self._model_index = index
        self.new_session()

    def _fill_models(self, models: list[str], selected: str) -> None:
        """List installed models, then the manage entry; keep selected, else prefer Clarke's preferred model."""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for name in models:
            self.model_combo.addItem(f"{name}  (preferred)" if name == PREFERRED_MODEL else name, name)
        if not self.model_combo.isEditable():
            self.model_combo.insertSeparator(self.model_combo.count())
            self.model_combo.addItem("Install or remove models…", MANAGE_MODELS)
        choice = selected if selected in models else PREFERRED_MODEL if PREFERRED_MODEL in models else models[0] if models else ""
        index = self.model_combo.findData(choice)
        if index < 0 and self.model_combo.isEditable():
            self.model_combo.setEditText(choice)
        self.model_combo.setCurrentIndex(index)
        self._model_index = index
        self.model_combo.blockSignals(False)

    def check_runtime(self) -> None:
        """Probe the selected CLI in a worker, without sending a project prompt."""
        if self.probe_worker is not None or self.worker is not None:
            return
        provider = self.runtime_combo.currentData()
        self.probe_worker = RuntimeProbe(provider, self.endpoint if descriptor(provider).needs_endpoint else "", self)
        self.probe_worker.probed.connect(self.on_probed)
        self.probe_worker.finished.connect(self.probe_finished)
        self.probe_worker.start()
        self.update_controls()

    def on_probed(self, status: RuntimeStatus) -> None:
        """Show the selected runtime's models, and say what is wrong when it is not ready."""
        if status.provider != self.runtime_combo.currentData():
            return
        self.runtime_status = status
        if status.endpoint:
            self.endpoint = status.endpoint
        self.notice_label.setText(status.message)
        self.notice.setVisible(not status.ready)
        selected = self.selected_model()
        models = list(status.models) if descriptor(status.provider).enumerates_models else [selected or "default"]
        if selected and selected not in models:
            models.insert(0, selected)
            if status.ready:
                self.notice_label.setText(f"The model {selected} is no longer installed. Install it again, or start a new conversation.")
                self.notice.show()
        self._fill_models(models, selected)
        self.update_controls()

    def probe_finished(self) -> None:
        worker = self.probe_worker
        self.probe_worker = None
        if worker:
            worker.deleteLater()
        self.update_controls()

    def new_session(self, *_args) -> None:
        """Clear the current conversation, when asked to or after a runtime or model change."""
        if self.controller:
            self.controller.cancel()
        self.controller = None
        self.session_directory = None
        self._draft_label = None
        self._process_card = None
        self._shown_sources = 0
        self._streamed_chars = 0
        self.conversation.clear_conversation()
        self.activity.clear()
        self.sources.clear()
        self.history_combo.setCurrentIndex(0)
        self.update_controls()

    def send(self) -> None:
        """Launch one model turn for the user's prompt, in the open project and on its focus run.

        The first turn creates the session, with or without a project open. A later turn keeps the
        conversation and moves it to the project and run shown now; with no project open, it stays
        where the conversation last was.
        """
        if not self.send_button.isEnabled():
            return
        prompt = self.input.toPlainText().strip()
        try:
            run_ids = self._selected_runs()
            if self.controller is None:
                context = SessionContext.create(
                    self.project.root_dir if self.project else None, run_ids, self.selected_model(), self.runtime_status.endpoint,
                    runtime=self.runtime_combo.currentData(), remote_acknowledged=self.remote_acknowledgement.isChecked(),
                    projects_dir=self.settings.default_projects_dir,
                )
                self.controller = AgentController(context, create_adapter(context.runtime, context.endpoint))
                self.session_directory = context.directory
            elif self.project is not None:
                self.controller.refocus(self.project.root_dir, run_ids)
            self.controller.cancelled.clear()
            self._draft_label = None
            self._streamed_chars = 0
            self._shown_sources = len(session_sources(self.session_directory))
            self.conversation.add_message("user", prompt)
            self._process_card = self.conversation.add_process()
            self._process_card.add_event(RuntimeEvent("info", "Starting agent turn…"))
            self.input.clear()
            self.worker = AgentWorker(self.controller, prompt, self)
            self.worker.event_received.connect(self.on_event)
            self.worker.answered.connect(self.on_answer)
            self.worker.finished.connect(self.finish_turn)
            self.worker.start()
            self.activity.appendPlainText("Starting agent turn…")
            self.update_controls()
        except (AgentError, OSError) as exc:
            self.activity.appendPlainText(str(exc))
            self.conversation.add_message("notice", str(exc))

    def _selected_runs(self) -> tuple[str, ...]:
        """Return the focus run of the open project, or nothing when it has none."""
        return (self.focus_run,) if self.project and self.focus_run else ()

    def on_event(self, event: RuntimeEvent) -> None:
        """Place each runtime step in the active chat turn and refresh audited source details."""
        if not self.worker or self.worker.controller is not self.controller:
            return
        if event.kind in ("tool_start", "tool_result", "session", "info", "reasoning"):
            detail = f" {event.data['input']}" if event.data.get("input") else ""
            self.activity.appendPlainText(f"{event.kind}: {event.text or 'Agent session started'}{detail}"[:2000])
            source = None
            if event.kind == "tool_result":
                records = session_sources(self.session_directory) if self.session_directory else []
                if self._shown_sources < len(records):
                    source = records[self._shown_sources]
                    self._shown_sources += 1
                self.update_sources()
            if self._process_card:
                self._process_card.add_event(event, source)
        elif event.kind == "text":
            if self._draft_label is None:
                self._draft_label = self.conversation.add_message("assistant", "")
            remaining = max(0, 256_000 - self._streamed_chars)
            delta = event.text[:remaining]
            self._draft_label.setText(self._draft_label.text() + delta)
            self._streamed_chars += len(delta)
            if len(delta) < len(event.text) and remaining:
                self._draft_label.setText(self._draft_label.text() + "\n[Output truncated in view; see conversation.md.]")
            self.conversation.scroll_to_latest()
        elif event.kind == "error":
            self.activity.appendPlainText(event.text)
            if self._process_card:
                self._process_card.add_event(event)
                self._process_card.complete()
            if self._draft_label:
                self._draft_label.setText("Turn failed: " + event.text)
                self._draft_label.flush()
            else:
                self.conversation.add_message("notice", event.text)

    def on_answer(self, answer: str) -> None:
        """Replace the draft bubble with the cited final answer and collapse the turn's process."""
        if not self.worker or self.worker.controller is not self.controller or not self.session_directory:
            return
        sources = session_sources(self.session_directory)
        final = cited_answer(answer, sources)
        if self._draft_label:
            self._draft_label.setText(final)
        else:
            self._draft_label = self.conversation.add_message("assistant", final)
        self._draft_label.flush()
        if self._process_card:
            turns = turn_accounting(self.session_directory)
            self._process_card.complete(turn_summary(turns[-1]) if turns and turns[-1]["outcome"] == "answered" else None)
        self.conversation.scroll_to_latest()
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

    def finish_turn(self) -> None:
        """Release the finished worker, refresh this tab, and tell the main window the agent may have changed runs."""
        if self._process_card:
            self._process_card.complete()
        self._process_card = None
        self._draft_label = None
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self.refresh_runs()
        self.refresh_history()
        self._show_pending_project()
        self.update_controls()
        self.turn_finished.emit()

    def stop(self) -> None:
        if self.worker:
            self.worker.controller.cancel()
            self.activity.appendPlainText("Stopping…")

    def update_controls(self) -> None:
        """Enable actions only when the runtime and model are ready."""
        busy = self.worker is not None
        probing = self.probe_worker is not None
        for control in (self.runtime_combo, self.model_combo, self.history_combo, self.new_button):
            control.setEnabled(not busy and not probing)
        self.remote_acknowledgement.setEnabled(not busy and not probing)
        self.stop_button.setEnabled(busy)
        prompt = self.input.toPlainText().strip()
        provider = descriptor(self.runtime_combo.currentData())
        ready = self.runtime_status is not None and self.runtime_status.ready and self.runtime_status.provider == provider.provider
        acknowledged = provider.route != "remote" or self.remote_acknowledgement.isChecked()
        model = self.selected_model()
        model_ready = not provider.enumerates_models or self.runtime_status is not None and model in self.runtime_status.models
        context = self.controller.context if self.controller else None
        # The project and run may differ from the session's: the next turn moves the session to them.
        scope_matches = context is None or (
            context.runtime == provider.provider and context.model == model
            and context.endpoint == (self.runtime_status.endpoint if self.runtime_status else "")
        )
        self.send_button.setEnabled(bool(not busy and not probing and ready and acknowledged and model_ready and scope_matches and model and prompt and len(prompt) <= MAX_PROMPT_CHARS))
        self.folder_button.setEnabled(self.session_directory is not None)
        self.export_button.setEnabled(not busy and self.session_directory is not None)
        scripts = proposed_scripts(self.session_directory)
        self.review_button.setText(f"Review proposed scripts ({scripts})" if scripts else "Review proposed scripts")
        self.review_button.setEnabled(not busy and scripts > 0)
        where = self.project.name if self.project else "no project"
        run = f" / {self.focus_run}" if self.project and self.focus_run else ""
        self.session_summary.setText(f"Clarke  ·  {model or 'No model'}  ·  {where}{run}")

    def export_audit(self) -> None:
        """Save the conversation's folder, without the runtime's internal files, as a ZIP the user names."""
        if not self.session_directory:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Export session", str(Path.home() / (self.session_directory.name + ".zip")), "ZIP archive (*.zip)")
        if destination:
            try:
                write_conversation_log(self.session_directory)
                export_session(self.session_directory, Path(destination))
                self.activity.appendPlainText("Session exported. It contains your questions, Clarke's answers, and grid data from your projects; treat it as sensitive.")
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

    def refresh_history(self) -> None:
        """List saved sessions of every project and keep the displayed session selected after a completed turn.

        Older sessions kept inside the open project are listed with them.
        """
        selected = str(self.session_directory) if self.session_directory else ""
        self.history_combo.clear()
        self.history_combo.addItem("New conversation", "")
        try:
            for path in saved_sessions(self.settings.default_projects_dir, self.project.root_dir if self.project else None):
                self.history_combo.addItem(session_title(path), str(path))
        except (AgentError, OSError):
            self.activity.appendPlainText("A session folder is not a regular directory.")
        index = self.history_combo.findData(selected)
        if selected and index < 0 and Path(selected).is_dir():
            self.history_combo.addItem(session_title(Path(selected)), selected)
            index = self.history_combo.count() - 1
        self.history_combo.setCurrentIndex(index if index >= 0 else 0)

    def open_history(self, index: int) -> None:
        """Restore a selected session's scope, transcript, and runtime state for follow-up turns."""
        directory = self.history_combo.itemData(index)
        if not directory:
            self.new_session()
            return
        if self.controller and self.controller.context.directory == Path(directory):
            return
        try:
            context = SessionContext.load(Path(directory) / "context.json")
            path = scoped_path(context.directory, "transcript.jsonl")
            if path.stat().st_size > 8 * 1024 * 1024:
                raise AgentError("SESSION_LIMIT", "Open the session folder to read this large conversation in conversation.md.")
            messages = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            records = session_sources(context.directory)
            events_path = scoped_path(context.directory, "runtime_events.jsonl")
            events = []
            if events_path.exists() and events_path.stat().st_size <= 8 * 1024 * 1024:
                events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            controller = AgentController(context, create_adapter(context.runtime, context.endpoint))
            controller.restore(messages, events)
        except (AgentError, OSError, ValueError) as exc:
            message = f"Could not load this session: {exc}"
            self.activity.appendPlainText(message)
            self.conversation.add_message("notice", message)
            current = self.history_combo.findData(str(self.session_directory)) if self.session_directory else 0
            self.history_combo.setCurrentIndex(max(0, current))
            return
        self.new_session()
        self._restore_session_controls(context)
        self.controller = controller
        self.session_directory = context.directory
        if not (context.directory / "conversation.md").exists():
            try:
                write_conversation_log(context.directory)
            except (AgentError, OSError):
                pass  # The log is a convenience; the session opens without it.
        self._render_saved_conversation(messages, events, records)
        self._shown_sources = len(records)
        self.update_sources()
        self.activity.setPlainText("Saved session loaded. Ask a follow-up once its runtime is ready.")
        if self.project is not None and context.project_root not in (None, self.project.root_dir):
            self.activity.appendPlainText(f"This conversation was last in {context.project_root}. The next question goes to {self.project.name}, the project open now.")
        self.history_combo.setCurrentIndex(index)
        self.check_runtime()
        self.update_controls()

    def _restore_session_controls(self, context: SessionContext) -> None:
        """Apply context's provider, model, endpoint, and run before open_history enables follow-ups.

        The run is focused only when the conversation was last in the project open now.
        """
        self.runtime_combo.blockSignals(True)
        self.runtime_combo.setCurrentIndex(self.runtime_combo.findData(context.runtime))
        self.runtime_combo.blockSignals(False)
        self.provider_changed(probe=False)
        self.endpoint = context.endpoint or DEFAULT_ENDPOINT
        models = [str(self.model_combo.itemData(index)) for index in range(self.model_combo.count()) if self.model_combo.itemData(index) not in (None, MANAGE_MODELS)]
        self._fill_models(models if context.model in models else [context.model, *models], context.model)
        if self.project is None or context.project_root != self.project.root_dir:
            return
        if context.run_ids and context.run_ids[0] in self.completed_runs():
            self.focus_run = context.run_ids[0]
            self._show_project_label()

    def _render_saved_conversation(self, messages: list[dict], events: list[dict], records: list[dict]) -> None:
        """Merge timestamped messages/events with audited records for open_history's chat replay."""
        timeline = [(item.get("timestamp", ""), 0 if item.get("role") == "user" else 2, "message", item) for item in messages]
        timeline.extend((item.get("timestamp", ""), 1, "event", item) for item in events if item.get("kind") in ("session", "info", "reasoning", "tool_start", "tool_result", "error"))
        timeline.sort(key=lambda item: (item[0], item[1]))
        summaries = {turn["ended_at"]: turn_summary(turn) for turn in turn_accounting(self.session_directory)} if self.session_directory else {}
        process = None
        source_index = 0
        for _, _, kind, item in timeline:
            if kind == "message":
                role = item.get("role", "notice")
                if role == "user":
                    if process:
                        process.complete()
                    self.conversation.add_message("user", str(item.get("text", "")))
                    process = self.conversation.add_process()
                else:
                    if process:
                        process.complete(summaries.get(item.get("timestamp")))
                        process = None
                    text = str(item.get("text", ""))
                    self.conversation.add_message(role, cited_answer(text, records) if role == "assistant" else text).flush()
            elif process:
                event = RuntimeEvent(str(item.get("kind", "")), str(item.get("text", "")), item.get("data") or {})
                source = None
                if event.kind == "tool_result" and source_index < len(records):
                    source = records[source_index]
                    source_index += 1
                process.add_event(event, source)
        if process:
            process.complete()
        self.conversation.scroll_to_latest(force=True)

    def open_session_folder(self) -> None:
        if self.session_directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session_directory)))

    def reference_documents_folder(self) -> Path:
        """Return the folder of reference documents Clarke searches, creating it so the user can fill it."""
        folder = reference_folder(Path(self.settings.default_projects_dir).expanduser())
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def open_reference_documents(self) -> None:
        try:
            folder = self.reference_documents_folder()
        except OSError as exc:
            QMessageBox.warning(self, "Reference documents", f"GridLens could not create the reference documents folder: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def shutdown(self) -> bool:
        self.stop()
        for worker, wait in ((self.worker, 12_000), (self.probe_worker, 12_000), (self.setup_probe, 35_000)):
            if worker and not worker.wait(wait):
                return False
        return True
