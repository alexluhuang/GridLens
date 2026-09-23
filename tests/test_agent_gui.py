from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gridlens.agent.controller import AgentController
from gridlens.agent.hermes import HermesAdapter
from gridlens.agent.runtime import RuntimeEvent, RuntimeStatus
from gridlens.agent.session import SessionContext
from gridlens.core.app_settings import AppSettings
from gridlens.core.project import Project
from gridlens.gui.agent_tab import AgentTab, cited_answer


def test_agent_tab_scope_plain_text_and_provider_guidance(agent_project):
    """Use a synthetic project to check provider controls and safe text rendering; pytest reads assertions."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_project))
    assert [tab.run_combo.itemData(index) for index in range(tab.run_combo.count())] == ["", "run_b", "run_a"]
    assert tab.run_combo.currentData() == "run_b"
    assert [tab.runtime_combo.itemData(index) for index in range(tab.runtime_combo.count())] == ["hermes", "claude", "codex"]
    assert "CEII" in tab.runtime_policy.text()
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", "http://127.0.0.1:11434", ("test:model",)))
    tab.input.setPlainText("Where are files?")
    assert tab.send_button.isEnabled()
    bubble = tab.conversation.add_message("assistant", '<img src="https://remote.invalid/data"> [T999]')
    assert bubble.textFormat() == Qt.PlainText
    assert '<img src="https://remote.invalid/data">' in bubble.text()
    tab.runtime_combo.blockSignals(True)
    tab.runtime_combo.setCurrentIndex(1)
    tab.runtime_combo.blockSignals(False)
    tab.provider_changed(probe=False)
    assert tab.route_badge.text() == "Remote"
    assert not tab.endpoint.isVisible()
    assert tab.model_combo.isEditable()
    tab.on_probed(RuntimeStatus(False, "Sign in", "/bin/claude", "2.1.278", provider="claude", route="remote", authenticated=False, login_command="claude auth login", docs_url="https://code.claude.com/docs/en/cli-usage"))
    assert tab.setup_command.text() == "claude auth login"
    assert "Sign in" in tab.setup_message.text()
    assert "CEII" in tab.runtime_policy.text()
    assert not tab.send_button.isEnabled()
    tab.on_probed(RuntimeStatus(True, "Ready", "/bin/claude", "2.1.278", models=("default",), provider="claude", route="remote", authenticated=True, docs_url="https://code.claude.com/docs/en/cli-usage"))
    tab.input.setPlainText("Where are files?")
    assert not tab.send_button.isEnabled()
    tab.remote_acknowledgement.setChecked(True)
    assert tab.send_button.isEnabled()
    tab.new_session()
    assert tab.conversation.messages() == []
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_streamed_answer_replaced_by_cited_final_and_sources_show_errors(agent_context):
    """Text deltas appear live, then one cited answer replaces them; audited errors stay visible."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_context.project_root))
    controller = object()
    tab.controller = controller
    tab.worker = SimpleNamespace(controller=controller)
    tab.session_directory = agent_context.directory
    tab.conversation.add_message("user", "Where is the line?")
    tab._process_card = tab.conversation.add_process()
    refreshes = []
    update_sources = tab.update_sources
    tab.update_sources = lambda: refreshes.append(True)
    tab.on_event(RuntimeEvent("text", "par"))
    tab.on_event(RuntimeEvent("text", "tial"))
    assert refreshes == []
    tab.on_event(RuntimeEvent("tool_result", "rank_branch_loading"))
    assert refreshes == [True]
    tab.update_sources = update_sources
    assert tab.conversation.messages()[-1] == ("assistant", "partial")
    records = [
        {"call_id": "T1", "phase": "completed", "tool": "rank_branch_loading", "outcome": "ok", "result": {"data": {"returned": 1, "total_matching": 3, "truncated": True, "offset": 0, "limit": 2, "inline_rows": 1, "result_file": "/s/results/T1.json", "rows_file": "/s/results/T1.csv", "analyzed_facility_count": 3, "filters": {"facility": "line"}}, "warnings": ["failed cases included"], "provenance": {"sources": [{"path": "runs/run_a/reports/table.csv"}]}}},
        {"call_id": "T2", "phase": "completed", "tool": "get_run_method", "outcome": "error", "result": {"error": {"code": "INVALID_ARTIFACT", "remedy": "Rebuild the cache."}}},
    ]
    (agent_context.directory / "tool_calls.jsonl").write_text("\n".join(json.dumps(row) for row in records) + "\n")
    tab.on_answer("final [T1] and [T99]")
    rendered = tab.conversation.messages()
    assert len([role for role, _ in rendered if role == "assistant"]) == 1
    assert "partial" not in rendered[-1][1]
    assert rendered[-1][1] == "final [T1] and [T99: invalid source]"
    assert "INVALID_ARTIFACT: Rebuild the cache." in tab.sources.toPlainText()
    assert "warning: failed cases included" in tab.sources.toPlainText()
    assert "facility" in tab.sources.toPlainText()
    assert "offset: 0; limit: 2" in tab.sources.toPlainText()
    assert "complete result: /s/results/T1.csv (1 rows shown inline)" in tab.sources.toPlainText()
    assert "matching facilities used: 3" in tab.sources.toPlainText()
    tab.worker = None
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_refresh_runs_does_not_retarget_active_turn(agent_context):
    """External run signals cannot replace the active worker's selected run."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_context.project_root))
    selected = tab.run_combo.currentData()
    tab.worker = SimpleNamespace(controller=SimpleNamespace(cancel=lambda: None))
    tab.select_run(agent_context.project_root / "runs" / "run_b")
    assert tab.run_combo.currentData() == selected
    tab.worker = None
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_conversation_can_start_without_a_project_and_shows_tool_arguments(tmp_path):
    """With no project open the agent can still be asked to create one; tool calls show their arguments."""
    app = QApplication.instance() or QApplication([])
    context = SessionContext.create(None, (), "test:model", "http://127.0.0.1:11434", projects_dir=tmp_path / "projects")
    tab = AgentTab(AppSettings(default_projects_dir=tmp_path / "projects"))
    assert "No project is open" in tab.project_label.text()
    assert tab.history_combo.findData(str(context.directory)) > 0
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", "http://127.0.0.1:11434", ("test:model",)))
    tab.input.setPlainText("Create a project from /data/case.raw and run it.")
    assert tab.send_button.isEnabled()
    assert not tab.build_button.isEnabled()
    controller = AgentController(context, HermesAdapter(context.endpoint))
    tab.controller = controller
    tab.session_directory = context.directory
    tab.worker = SimpleNamespace(controller=controller)
    tab.conversation.add_message("user", tab.input.toPlainText())
    tab._process_card = tab.conversation.add_process()
    tab.on_event(RuntimeEvent("tool_start", "mcp__gridlens__create_project", {"input": '{"name": "Study"}'}))
    assert 'tool_start: mcp__gridlens__create_project {"name": "Study"}' in tab.activity.toPlainText()
    assert 'Calling create_project\n{"name": "Study"}' in tab._process_card.plain_text()
    finished = []
    tab.turn_finished.connect(lambda: finished.append(True))
    tab.worker = None
    tab.finish_turn()
    assert finished == [True]
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_saved_conversation_replays_messages_and_tool_steps_in_order(agent_context, monkeypatch):
    """Reopen a saved audit with its tool steps, scope, and runtime continuation ready for another turn."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_context.project_root))
    tab.check_runtime = lambda: None
    messages = [
        {"timestamp": "2026-09-23T00:00:00.000+00:00", "role": "user", "text": "Which line is congested?"},
        {"timestamp": "2026-09-23T00:00:00.004+00:00", "role": "assistant", "text": "ALPHA to BETA: 120% [T1]."},
    ]
    events = [
        {"timestamp": "2026-09-23T00:00:00.001+00:00", "kind": "tool_start", "text": "mcp__gridlens__rank_branch_loading", "data": {"input": '{"limit": 1}'}},
        {"timestamp": "2026-09-23T00:00:00.003+00:00", "kind": "tool_result", "text": "mcp__gridlens__rank_branch_loading", "data": {}},
        {"timestamp": "2026-09-23T00:00:00.005+00:00", "kind": "completed", "text": "", "data": {"session_id": "hermes-123"}},
    ]
    records = [{"call_id": "T1", "phase": "completed", "tool": "rank_branch_loading", "outcome": "ok", "result": {"data": {"returned": 1, "total_matching": 3, "truncated": True}}}]
    for name, rows in (("transcript.jsonl", messages), ("runtime_events.jsonl", events), ("tool_calls.jsonl", records)):
        (agent_context.directory / name).write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    tab.refresh_history()
    index = tab.history_combo.findData(str(agent_context.directory))
    assert index > 0
    tab.open_history(index)
    assert tab.conversation.messages() == [("user", "Which line is congested?"), ("assistant", "ALPHA to BETA: 120% [T1].")]
    assert "[T1] 1 of 3 rows returned; result truncated" in tab.conversation.processes()[0].plain_text()
    assert tab.controller.context.directory == agent_context.directory
    assert tab.controller.continuation == "hermes-123"
    assert (tab.run_combo.currentData(), tab.compare_combo.currentData()) == ("run_a", "run_b")
    assert tab.model_combo.currentText() == "fixture:model"
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", agent_context.endpoint, ("fixture:model",)))
    tab.input.setPlainText("What about the next line?")
    assert tab.send_button.isEnabled()
    assert tab.history_combo.currentData() == str(agent_context.directory)
    resumed = tab.controller
    worker = MagicMock()
    monkeypatch.setattr("gridlens.gui.agent_tab.AgentWorker", lambda *_args: worker)
    tab.send()
    assert tab.controller is resumed
    assert tab.session_directory == agent_context.directory
    assert tab.conversation.messages()[-1] == ("user", "What about the next line?")
    tab.worker = None
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_finished_turn_keeps_active_conversation_selected_and_continuable(agent_context, monkeypatch):
    """Refresh the session list after a turn without switching the visible chat to a history preview."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_context.project_root))
    for combo, run_id in ((tab.run_combo, "run_a"), (tab.compare_combo, "run_b")):
        combo.setCurrentIndex(combo.findData(run_id))
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", agent_context.endpoint, ("fixture:model",)))
    controller = AgentController(agent_context, HermesAdapter(agent_context.endpoint))
    tab.controller = controller
    tab.session_directory = agent_context.directory
    tab.conversation.add_message("user", "First question")
    tab.conversation.add_message("assistant", "First answer")
    tab.worker = SimpleNamespace(deleteLater=lambda: None)
    tab.finish_turn()
    assert tab.history_combo.currentData() == str(agent_context.directory)
    index = tab.history_combo.currentIndex()
    tab.open_history(index)
    assert tab.controller is controller
    assert tab.conversation.messages() == [("user", "First question"), ("assistant", "First answer")]
    tab.input.setPlainText("Follow-up question")
    assert tab.send_button.isEnabled()
    controller.cancel()
    worker = MagicMock()
    monkeypatch.setattr("gridlens.gui.agent_tab.AgentWorker", lambda *_args: worker)
    tab.send()
    assert tab.controller is controller
    assert tab.session_directory == agent_context.directory
    assert not controller.cancelled.is_set()
    tab.worker = None
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_runtime_recheck_keeps_chat_when_saved_model_is_unavailable(agent_context):
    """Preserve the active transcript when an installed-model refresh no longer lists its model."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_context.project_root))
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", agent_context.endpoint, ("fixture:model",)))
    for combo, run_id in ((tab.run_combo, "run_a"), (tab.compare_combo, "run_b")):
        combo.setCurrentIndex(combo.findData(run_id))
    tab.controller = AgentController(agent_context, HermesAdapter(agent_context.endpoint))
    tab.session_directory = agent_context.directory
    tab.conversation.add_message("user", "First question")
    tab.conversation.add_message("assistant", "First answer")
    tab.input.setPlainText("Follow-up question")
    assert tab.send_button.isEnabled()
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", agent_context.endpoint, ("other:model",)))
    assert tab.conversation.messages() == [("user", "First question"), ("assistant", "First answer")]
    assert tab.model_combo.currentText() == "fixture:model"
    assert "unavailable" in tab.setup_message.text()
    assert not tab.send_button.isEnabled()
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_live_tool_results_keep_their_own_audited_source_when_events_queue(agent_context):
    """Match each queued result event to its own audited call rather than the latest file row."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.session_directory = agent_context.directory
    controller = object()
    tab.controller = controller
    tab.worker = SimpleNamespace(controller=controller)
    tab._process_card = tab.conversation.add_process()
    records = [
        {"call_id": "T1", "phase": "completed", "result": {"data": {"returned": 1, "total_matching": 3}}},
        {"call_id": "T2", "phase": "completed", "result": {"data": {"returned": 2, "total_matching": 4}}},
    ]
    (agent_context.directory / "tool_calls.jsonl").write_text("\n".join(json.dumps(row) for row in records) + "\n")
    for _ in records:
        tab.on_event(RuntimeEvent("tool_result", "mcp__gridlens__rank_branch_loading"))
    detail = tab._process_card.plain_text()
    assert "[T1] 1 of 3 rows returned" in detail
    assert "[T2] 2 of 4 rows returned" in detail
    tab.worker = None
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_unknown_citations_are_marked():
    assert cited_answer("120% [T1], claim [T999]", [{"call_id": "T1"}]) == "120% [T1], claim [T999: invalid source]"
    assert cited_answer("120% [Call\u202fT1]", [{"call_id": "T1"}]) == "120% [T1]"
