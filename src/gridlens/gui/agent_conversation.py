"""Chat cards for the Agent tab's messages and observable process steps.

The agent's answers are rendered as Markdown, because many models write it; the user's messages and
GridLens notices stay plain text. Rendering never fetches anything: raw HTML is shown as text, images are
replaced by their alt text, and links are shown as text that cannot be opened, so an answer cannot make
GridLens reach the network or read a file.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from gridlens.agent.runtime import RuntimeEvent


# While an answer streams, it is rendered at most this often; flush() renders at once.
RENDER_INTERVAL_MS = 80
# Within this many pixels of the bottom, the conversation keeps following new text.
FOLLOW_MARGIN_PX = 40
MARKDOWN_FEATURES = QTextDocument.MarkdownFeature(
    QTextDocument.MarkdownFeature.MarkdownDialectGitHub.value | QTextDocument.MarkdownFeature.MarkdownNoHTML.value
)
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d{1,9}[.)])\s")
# A line that starts a block of its own: a list item, heading, quote, table row, or code fence.
BLOCK_START = re.compile(r"^\s{0,3}(?:[-*+]\s|\d{1,9}[.)]\s|#{1,6}(?:\s|$)|>|\||```|~~~)")
TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$|^\s*\|\s*:?-+:?\s*\|\s*$")
BODY_STYLE = re.compile(r"<body[^>]*>")


def _markdown_source(text: str) -> str:
    """Prepare an answer for the Markdown parser so it reads as its writer laid it out.

    Outside fenced code: a table or list starts a new block even without a blank line before it, a plain
    line after a table or a list item ends it rather than joining it, and each remaining single newline
    stays a line break (two trailing spaces) instead of joining two lines of one paragraph, as plain-text
    answers and GridLens notes expect.
    """
    lines = text.split("\n")
    structured: list[str] = []
    fenced = in_table = False
    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            previous = structured[-1] if structured else ""
            if not line.strip():
                in_table = False
            elif previous.strip():
                header = "|" in line and bool(TABLE_DELIMITER.match(following))
                ends_table = in_table and "|" not in line
                ends_list = bool(LIST_ITEM.match(previous)) and not line[:1].isspace() and not BLOCK_START.match(line)
                if (header and not in_table) or ends_table or ends_list:
                    structured.append("")
                in_table = (in_table and not ends_table) or header
        structured.append(line)
    fenced = False
    for index, line in enumerate(structured[:-1]):
        if FENCE.match(line):
            fenced = not fenced
            continue
        following = structured[index + 1]
        if fenced or not line.strip() or not following.strip() or "|" in line or BLOCK_START.match(following):
            continue
        if not line.endswith(("  ", "\\")):
            structured[index] = line + "  "
    return "\n".join(structured)


def markdown_html(text: str) -> str:
    """Render Markdown to HTML that references nothing outside itself.

    Raw HTML is not parsed, so it shows as literal text. Each image becomes its alt text, and each link
    keeps its text but loses its target, so nothing in the result can load or open a resource.
    """
    document = QTextDocument()
    document.setMarkdown(_markdown_source(text), MARKDOWN_FEATURES)
    images, links = [], []
    block = document.begin()
    while block.isValid():
        fragments = block.begin()
        while not fragments.atEnd():
            fragment = fragments.fragment()
            char_format = fragment.charFormat()
            if char_format.isImageFormat():
                images.append((fragment.position(), fragment.length(), char_format))
            elif char_format.isAnchor() or char_format.anchorHref():
                links.append((fragment.position(), fragment.length(), char_format))
            fragments += 1
        block = block.next()
    cursor = QTextCursor(document)
    for position, length, char_format in links:
        cursor.setPosition(position)
        cursor.setPosition(position + length, QTextCursor.KeepAnchor)
        char_format.setAnchor(False)
        char_format.setAnchorHref("")
        char_format.setAnchorNames([])
        char_format.clearForeground()
        char_format.setFontUnderline(True)
        cursor.setCharFormat(char_format)
    # Replace images last to first, so the positions of the earlier ones still hold.
    for position, length, char_format in reversed(images):
        alt = str(char_format.property(QTextFormat.Property.ImageAltText) or "").strip()
        cursor.setPosition(position)
        cursor.setPosition(position + length, QTextCursor.KeepAnchor)
        cursor.insertText(f"[image: {alt}]" if alt else "[image]", QTextCharFormat())
    # The label's own font and color apply, not the document's defaults.
    return BODY_STYLE.sub("<body>", document.toHtml(), count=1)


class MessageBody(QLabel):
    """One message's text: plain, or Markdown rendered safely and at most every RENDER_INTERVAL_MS.

    text() and setText() always carry the raw source, so a streamed answer can grow one piece at a time.
    """

    def __init__(self, text: str = "", *, markdown: bool = False) -> None:
        """Create a selectable, word-wrapped body; markdown chooses rendered Markdown over plain text."""
        super().__init__()
        self.setObjectName("agentMessageBody")
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setOpenExternalLinks(False)
        self.setTextFormat(Qt.RichText if markdown else Qt.PlainText)
        self.markdown = markdown
        self._raw = ""
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RENDER_INTERVAL_MS)
        self._timer.timeout.connect(self._render_pending)
        self.setText(text)

    def text(self) -> str:  # noqa: D401 - QLabel override
        """Return the raw source text, not the rendered HTML."""
        return self._raw

    def setText(self, text: str) -> None:  # noqa: N802 - QLabel override
        """Replace the raw text; Markdown renders now, then at most once per interval while it keeps changing."""
        self._raw = text
        if not self.markdown:
            super().setText(text)
            return
        self._dirty = True
        if not self._timer.isActive():
            self._render()
            # An empty draft waits for its first words, which then render at once.
            if text:
                self._timer.start()

    def flush(self) -> None:
        """Render any pending text now, as a finished answer or a test needs."""
        self._timer.stop()
        if self._dirty:
            self._render()

    def rendered(self) -> str:
        """Return what the label displays: the raw text, or the rendered HTML for Markdown."""
        return super().text()

    def _render_pending(self) -> None:
        """Render the text that arrived since the last render, if any."""
        if self._dirty:
            self._render()
            self._timer.start()

    def _render(self) -> None:
        """Show the current raw text as rendered Markdown."""
        self._dirty = False
        super().setText(markdown_html(self._raw))


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
        self.empty_label = QLabel("Ask Clarke about a run, a project, or your analysis files.")
        self.empty_label.setObjectName("agentEmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.rows.addWidget(self.empty_label)
        self.rows.addStretch(1)
        self.setWidget(self.content)
        self._messages: list[tuple[str, MessageBody]] = []
        self._processes: list[ProcessCard] = []
        # Follow new content only while the reader is at the bottom; scrolling up stops following.
        self._following = True
        scrollbar = self.verticalScrollBar()
        scrollbar.valueChanged.connect(self._scrolled)
        scrollbar.rangeChanged.connect(self._range_changed)

    def _scrolled(self, value: int) -> None:
        """Follow new content again once the reader is back at the bottom, and stop when they leave it."""
        self._following = value >= self.verticalScrollBar().maximum() - FOLLOW_MARGIN_PX

    def _range_changed(self, _minimum: int, maximum: int) -> None:
        """Keep the newest content in view as the timeline grows, if the reader was following it."""
        if self._following:
            self.verticalScrollBar().setValue(maximum)

    @property
    def following(self) -> bool:
        """Return whether new content scrolls into view, which it does while the reader is at the bottom."""
        return self._following

    def clear_conversation(self) -> None:
        """Remove all cards and restore the empty prompt when AgentTab starts a new session."""
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.empty_label = QLabel("Ask Clarke about a run, a project, or your analysis files.")
        self.empty_label.setObjectName("agentEmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.rows.insertWidget(0, self.empty_label)
        self._messages.clear()
        self._processes.clear()
        self._following = True

    def add_message(self, role: str, text: str) -> MessageBody:
        """Add a role bubble and return its body for AgentTab's streaming updates.

        The agent's answers render as Markdown; the user's messages and notices stay plain text. A user
        message starts a turn, so it scrolls the conversation to the bottom.
        """
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
        body = MessageBody(text, markdown=role == "assistant")
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
        if role == "user":
            self.scroll_to_latest(force=True)
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
        """Insert a chat row above the stretch; it scrolls into view only if the reader is following."""
        self.empty_label.hide()
        self.rows.insertWidget(self.rows.count() - 1, row)
        self.scroll_to_latest()

    def scroll_to_latest(self, force: bool = False) -> None:
        """Show the newest content if the reader is following it, or always when force is True.

        force also resumes following, as a new turn or an opened conversation should. The jump is repeated
        once Qt has laid out new rows, in case they have not changed the scroll range yet.
        """
        if force:
            self._following = True
        if self._following:
            self._jump_to_bottom()
            QTimer.singleShot(0, self, self._jump_if_following)

    def _jump_if_following(self) -> None:
        """Jump to the bottom after layout, unless the reader has scrolled away since."""
        if self._following:
            self._jump_to_bottom()

    def _jump_to_bottom(self) -> None:
        """Set the scroll bar to its maximum."""
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def messages(self) -> list[tuple[str, str]]:
        """Return role and raw text pairs for GUI tests and AgentTab's checks."""
        return [(role, label.text()) for role, label in self._messages]

    def processes(self) -> list[ProcessCard]:
        """Return process cards for history and GUI tests without exposing layout internals."""
        return list(self._processes)
