"""Plain-text chat cards for the Agent tab's messages and observable process steps."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from gridlens.agent.runtime import RuntimeEvent


class AgentPromptEdit(QPlainTextEdit):
    """A chat composer that sends on Enter and inserts a newline on Shift+Enter."""

    submitted = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Emit submitted for an unshifted Return key; otherwise let QPlainTextEdit edit text."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ProcessCard(QFrame):
    """Show one turn's available reasoning and tool events in a collapsible chat card."""

    def __init__(self) -> None:
        """Create an expanded process card; ConversationView inserts it beside the turn's messages."""
        super().__init__()
        self.setObjectName("agentProcessCard")
        self.tool_count = 0
        self._steps: list[str] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        self.toggle = QToolButton()
        self.toggle.setObjectName("agentProcessToggle")
        self.toggle.setText("Working · 0 tools")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setArrowType(Qt.DownArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        layout.addWidget(self.toggle)
        self.details = QWidget()
        self.details.setObjectName("agentProcessDetails")
        self.details_layout = QVBoxLayout(self.details)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_layout.setSpacing(6)
        self.reasoning = QLabel("Reasoning text has not been provided by this runtime.")
        self.reasoning.setObjectName("agentReasoningNote")
        self.reasoning.setTextFormat(Qt.PlainText)
        self.reasoning.setWordWrap(True)
        self.reasoning.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details_layout.addWidget(self.reasoning)
        layout.addWidget(self.details)
        self.toggle.toggled.connect(self._set_expanded)

    def _set_expanded(self, expanded: bool) -> None:
        """Show or hide details from the toggle state and set its direction for ProcessCard."""
        self.details.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def add_event(self, event: RuntimeEvent, source: dict | None = None) -> None:
        """Append a runtime event and optional audited source; AgentTab calls this as events arrive."""
        if event.kind == "reasoning":
            previous = "" if self.reasoning.text().startswith("Reasoning text has not") else self.reasoning.text()
            self.reasoning.setText((previous + event.text)[:16_000])
            return
        if event.kind == "tool_start":
            self.tool_count += 1
            name = event.text.rsplit("__", 1)[-1]
            detail = str(event.data.get("input") or "")[:2000]
            self._add_step(f"Calling {name}", detail)
        elif event.kind == "tool_result":
            name = event.text.rsplit("__", 1)[-1]
            status = "Failed" if event.data.get("is_error") else "Completed"
            detail = ""
            if source:
                result = source.get("result") or {}
                data = result.get("data") or {}
                error = result.get("error") or {}
                detail = f"[{source.get('call_id', '?')}] "
                if error:
                    detail += f"{error.get('code', 'error')}: {error.get('remedy', '')}"
                else:
                    if "returned" in data and "total_matching" in data:
                        detail += f"{data['returned']:,} of {data['total_matching']:,} rows returned"
                    if data.get("truncated"):
                        detail += "; result truncated"
                    if data.get("result_file"):
                        detail += f"\nComplete result: {data.get('rows_file') or data['result_file']}"
                        detail += f" ({data.get('inline_rows', 0)} rows shown inline)"
                    paths = [str(item.get("path", "")) for item in (result.get("provenance") or {}).get("sources") or []]
                    if paths:
                        detail += "\nSources: " + ", ".join(paths[:3])
            self._add_step(f"{status} {name}", detail[:3000])
        elif event.kind in ("session", "info", "error"):
            self._add_step(event.text or ("Agent session started" if event.kind == "session" else event.kind.title()))
        self.toggle.setText(f"Working · {self.tool_count} tool{'s' if self.tool_count != 1 else ''}")

    def _add_step(self, title: str, detail: str = "") -> None:
        """Add selectable plain text to this card and retain it for ConversationView inspection."""
        block = QFrame()
        block.setObjectName("agentProcessStep")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(3)
        for value, name in ((title, "agentProcessStepTitle"), (detail, "agentProcessStepDetail")):
            if value:
                label = QLabel(value)
                label.setObjectName(name)
                label.setTextFormat(Qt.PlainText)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                layout.addWidget(label)
        self.details_layout.addWidget(block)
        self._steps.append(title + ("\n" + detail if detail else ""))

    def complete(self) -> None:
        """Collapse a finished turn's process detail while keeping its tool count visible in chat."""
        self.toggle.setText(f"Process · {self.tool_count} tool{'s' if self.tool_count != 1 else ''}")
        self.toggle.setChecked(False)

    def plain_text(self) -> str:
        """Return visible process text for conversation checks and accessibility tests."""
        return "\n".join([self.reasoning.text(), *self._steps])


class ConversationView(QScrollArea):
    """Keep user bubbles, agent replies, and process cards in one scrollable timeline."""

    def __init__(self) -> None:
        """Build a top-aligned chat timeline for AgentTab's live and saved messages."""
        super().__init__()
        self.setObjectName("agentConversation")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("agentConversationContent")
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(24, 22, 24, 22)
        self.rows.setSpacing(14)
        self.empty_label = QLabel("Ask GridLens about a run, a project, or your analysis files.")
        self.empty_label.setObjectName("agentEmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.rows.addWidget(self.empty_label)
        self.rows.addStretch(1)
        self.setWidget(self.content)
        self._messages: list[tuple[str, QLabel]] = []
        self._processes: list[ProcessCard] = []

    def clear_conversation(self) -> None:
        """Remove all cards and restore the empty prompt when AgentTab starts a new session."""
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.empty_label = QLabel("Ask GridLens about a run, a project, or your analysis files.")
        self.empty_label.setObjectName("agentEmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.rows.insertWidget(0, self.empty_label)
        self._messages.clear()
        self._processes.clear()

    def add_message(self, role: str, text: str) -> QLabel:
        """Add a plain-text role bubble and return its label for AgentTab's streaming updates."""
        title = "You" if role == "user" else "GridLens Agent" if role == "assistant" else "GridLens"
        card = QFrame()
        card.setObjectName("agentUserMessage" if role == "user" else "agentAssistantMessage" if role == "assistant" else "agentNoticeMessage")
        card.setMaximumWidth(650 if role == "user" else 800)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("agentMessageHeading")
        body = QLabel(text)
        body.setObjectName("agentMessageBody")
        body.setTextFormat(Qt.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(heading)
        layout.addWidget(body)
        row = QWidget()
        row.setObjectName("agentConversationRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row_layout.addStretch(1)
        row_layout.addWidget(card, 3)
        if role != "user":
            row_layout.addStretch(1)
        self._insert(row)
        self._messages.append((role, body))
        return body

    def add_process(self) -> ProcessCard:
        """Insert and return a process card between a user prompt and the agent's answer."""
        card = ProcessCard()
        card.setMaximumWidth(800)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row = QWidget()
        row.setObjectName("agentConversationRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(card, 3)
        row_layout.addStretch(1)
        self._insert(row)
        self._processes.append(card)
        return card

    def _insert(self, row: QWidget) -> None:
        """Insert a chat row above the stretch and keep the latest row in view."""
        self.empty_label.hide()
        self.rows.insertWidget(self.rows.count() - 1, row)
        self.scroll_to_latest()

    def scroll_to_latest(self) -> None:
        """Scroll to the newest card after Qt recalculates layout geometry."""
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def messages(self) -> list[tuple[str, str]]:
        """Return role/text pairs for GUI tests and AgentTab's plain-text checks."""
        return [(role, label.text()) for role, label in self._messages]

    def processes(self) -> list[ProcessCard]:
        """Return process cards for history and GUI tests without exposing layout internals."""
        return list(self._processes)
