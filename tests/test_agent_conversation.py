from __future__ import annotations

import os
import re
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from gridlens.agent.runtime import RuntimeEvent
from gridlens.gui.agent_conversation import AgentPromptEdit, ConversationView


def test_chat_timeline_keeps_messages_and_tool_evidence_in_one_scroll_area():
    """Exercise safe message text, visible audited tool steps, collapse, and conversation reset."""
    app = QApplication.instance() or QApplication([])
    view = ConversationView()
    view.resize(760, 500)
    user = view.add_message("user", '<img src="https://remote.invalid/data">')
    process = view.add_process()
    process.add_event(RuntimeEvent("tool_start", "mcp__gridlens__rank_branch_loading", {"input": '{"limit": 5}'}))
    process.add_event(RuntimeEvent("tool_result", "mcp__gridlens__rank_branch_loading"), {
        "call_id": "T1", "result": {"data": {"returned": 5, "total_matching": 6823, "truncated": True,
        "result_file": "agent/results/T1.json", "rows_file": "agent/results/T1.csv", "inline_rows": 2},
        "provenance": {"sources": [{"path": "runs/run_a/reports/interactive_tables/pflow_mm.csv"}]}}
    })
    agent = view.add_message("assistant", "Five lines [T1].")
    view.show()
    app.processEvents()
    assert user.textFormat() == Qt.PlainText
    assert '<img src="https://remote.invalid/data">' in user.text()
    assert view.messages() == [("user", user.text()), ("assistant", agent.text())]
    assert "[T1] 5 of 6,823 rows returned; result truncated" in process.plain_text()
    assert "Complete result: agent/results/T1.csv (2 rows shown inline)" in process.plain_text()
    assert "pflow_mm.csv" in process.plain_text()
    assert "Reasoning text has not been provided" in process.plain_text()
    process.complete()
    assert not process.details.isVisible()
    assert process.toggle.text() == "Process · 1 tool"
    process.toggle.setChecked(True)
    assert process.details.isVisible()
    view.clear_conversation()
    app.processEvents()
    assert view.messages() == [] and view.processes() == []
    assert view.empty_label.isVisible()
    view.close()
    view.deleteLater()
    app.processEvents()


def test_chat_timeline_displays_only_supplied_reasoning_text():
    """A provider-supplied reasoning event replaces the unavailable notice without inventing steps."""
    app = QApplication.instance() or QApplication([])
    view = ConversationView()
    process = view.add_process()
    process.add_event(RuntimeEvent("reasoning", "Checking line loading"))
    process.add_event(RuntimeEvent("reasoning", " against the run cache."))
    assert process.reasoning.text() == "Checking line loading against the run cache."
    assert "not been provided" not in process.plain_text()
    view.close()
    view.deleteLater()
    app.processEvents()


def test_chat_composer_sends_on_enter_and_keeps_shift_enter_for_newlines():
    """Check the chat-style keyboard action without starting a model or changing the prompt text."""
    app = QApplication.instance() or QApplication([])
    editor = AgentPromptEdit()
    editor.show()
    editor.setFocus()
    spy = QSignalSpy(editor.submitted)
    QTest.keyClicks(editor, "First line")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
    QTest.keyClicks(editor, "Second line")
    assert editor.toPlainText() == "First line\nSecond line"
    assert spy.count() == 0
    QTest.keyClick(editor, Qt.Key_Return)
    assert spy.count() == 1
    assert editor.toPlainText() == "First line\nSecond line"
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_agent_answers_render_markdown_and_other_messages_stay_plain_text():
    """Tables, emphasis, and lists render for the agent; user text and notices are shown as typed."""
    app = QApplication.instance() or QApplication([])
    view = ConversationView()
    source = "**Key findings**\n\n| Facility | Loading |\n|---|---:|\n| BASTROP 6 2 | 360.86% |\n\n- first\n- second"
    agent = view.add_message("assistant", source)
    user = view.add_message("user", "**not bold**")
    notice = view.add_message("notice", "| a | b |")
    rendered = agent.rendered()
    assert agent.textFormat() == Qt.RichText
    assert "<table" in rendered and "360.86%" in rendered and "font-weight:700" in rendered and "<li" in rendered
    assert agent.text() == source
    assert user.textFormat() == Qt.PlainText and user.rendered() == "**not bold**"
    assert notice.textFormat() == Qt.PlainText
    assert view.messages() == [("assistant", source), ("user", "**not bold**"), ("notice", "| a | b |")]
    view.deleteLater()
    app.processEvents()


def test_rendered_answers_load_nothing_and_open_nothing():
    """Raw HTML stays text, images become their alt text, and links lose their targets."""
    app = QApplication.instance() or QApplication([])
    view = ConversationView()
    agent = view.add_message("assistant", '<img src="https://remote.invalid/data"> ![grid map](https://remote.invalid/map.png) ![ref][r] [open](file:///etc/passwd)\n\n[r]: https://remote.invalid/r.png')
    rendered = agent.rendered()
    assert "<img" not in rendered
    assert "&lt;img src=&quot;https://remote.invalid/data&quot;&gt;" in rendered
    assert "[image: grid map]" in rendered and "[image: ref]" in rendered
    assert "href" not in rendered and "file:///etc/passwd" not in rendered and "open" in rendered
    assert "remote.invalid/map.png" not in rendered and "remote.invalid/r.png" not in rendered
    assert not agent.openExternalLinks()
    view.deleteLater()
    app.processEvents()


def test_single_newlines_stay_line_breaks_and_lists_and_tables_end_cleanly():
    """GridLens notes join lines with one newline; each line stays its own line when rendered."""
    from gridlens.gui.agent_conversation import _markdown_source, markdown_html

    def paragraphs(html: str) -> list[str]:
        return re.findall(r"<p[^>]*>(.*?)</p>", html)

    assert paragraphs(markdown_html("[T1] listed 5 of 9 lines.\nIt was asked for 5.")) == ["[T1] listed 5 of 9 lines.", "It was asked for 5."]
    html = markdown_html("Control areas:\n- North: 45%\n- South: 40%\nEach average covers every facility.")
    assert html.count("<li") == 2 and "Each average covers every facility.</p>" in html
    html = markdown_html("Findings:\n| a | b |\n|---|---|\n| 1 | 2 |\nSources: [T1]")
    assert html.count("<tr") == 2 and "Sources: [T1]</p>" in html
    code = "```\ncode a\ncode b\n```"
    assert _markdown_source(code) == code
    assert "<pre" in markdown_html(code)


def test_streamed_markdown_renders_coalesced_and_flush_renders_at_once():
    """Streaming updates render at most once per interval; flush shows the full text immediately."""
    app = QApplication.instance() or QApplication([])
    view = ConversationView()
    body = view.add_message("assistant", "")
    body.setText("**Par")
    assert "Par" in body.rendered()
    body.setText(body.text() + "tial**")
    body.setText(body.text() + " answer")
    assert body.text() == "**Partial** answer"
    assert "answer" not in body.rendered()
    body.flush()
    assert "answer" in body.rendered() and "font-weight:700" in body.rendered()
    body.setText(body.text() + " more")
    QTest.qWait(250)
    assert "more" in body.rendered()
    view.deleteLater()
    app.processEvents()


def _settle(app) -> None:
    """Let Qt lay out new rows and update the scroll range."""
    for _ in range(3):
        QTest.qWait(10)
        app.processEvents()


def test_reader_can_scroll_freely_while_the_answer_streams():
    """New text keeps the view at the bottom only while the reader is there; a new question jumps back."""
    app = QApplication.instance() or QApplication([])
    view = ConversationView()
    view.resize(500, 300)
    view.show()
    for index in range(8):
        view.add_message("user", f"Question {index}")
        view.add_message("assistant", "Answer line.\n" * 6)
    body = view.add_message("assistant", "Streaming")
    _settle(app)
    scrollbar = view.verticalScrollBar()
    assert scrollbar.maximum() > 0 and scrollbar.value() == scrollbar.maximum() and view.following

    scrollbar.setValue(0)
    assert not view.following
    for _ in range(5):
        body.setText(body.text() + "\nmore text")
        body.flush()
        view.scroll_to_latest()
        _settle(app)
    assert scrollbar.value() == 0
    view.add_process().add_event(RuntimeEvent("tool_start", "mcp__gridlens__rank"))
    _settle(app)
    assert scrollbar.value() == 0

    scrollbar.setValue(scrollbar.maximum())
    assert view.following
    body.setText(body.text() + "\nstill more\nand more\nand more")
    body.flush()
    _settle(app)
    assert scrollbar.value() == scrollbar.maximum()

    scrollbar.setValue(0)
    view.add_message("user", "Next question")
    _settle(app)
    assert view.following and scrollbar.value() == scrollbar.maximum()
    view.close()
    view.deleteLater()
    app.processEvents()
