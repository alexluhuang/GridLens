from __future__ import annotations

import os
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
