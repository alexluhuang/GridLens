from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from gridlens.agent.runtime import RuntimeEvent, RuntimeStatus
from gridlens.core.project import Project
from gridlens.gui.agent_tab import AgentTab, cited_answer


def test_agent_tab_scope_plain_text_and_provider_guidance(agent_project):
    """Use a synthetic project to check provider controls and safe text rendering; pytest reads assertions."""
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_project))
    assert tab.run_combo.count() == 2
    assert [tab.runtime_combo.itemData(index) for index in range(tab.runtime_combo.count())] == ["hermes", "claude", "codex"]
    assert "CEII" in tab.runtime_policy.text()
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", "http://127.0.0.1:11434", ("test:model",)))
    tab.input.setPlainText("Where are files?")
    assert tab.send_button.isEnabled()
    tab.transcript.setPlainText('<img src="https://remote.invalid/data"> [T999]')
    assert '<img src="https://remote.invalid/data">' in tab.transcript.toPlainText()
    assert '<img src=' not in tab.transcript.document().toHtml()
    assert '&lt;img' in tab.transcript.document().toHtml()
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
    assert not tab.transcript.toPlainText()
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
    tab._parts = ["You\nWhere is the line?"]
    tab.transcript.setPlainText(tab._parts[0])
    refreshes = []
    update_sources = tab.update_sources
    tab.update_sources = lambda: refreshes.append(True)
    tab.on_event(RuntimeEvent("text", "par"))
    tab.on_event(RuntimeEvent("text", "tial"))
    assert refreshes == []
    tab.on_event(RuntimeEvent("tool_result", "rank_branch_loading"))
    assert refreshes == [True]
    tab.update_sources = update_sources
    assert "Agent\npartial" in tab.transcript.toPlainText()
    records = [
        {"call_id": "T1", "phase": "completed", "tool": "rank_branch_loading", "outcome": "ok", "result": {"data": {"returned": 1, "total_matching": 1, "truncated": False, "filters": {"facility": "line"}}, "warnings": ["failed cases included"], "provenance": {"sources": [{"path": "runs/run_a/reports/table.csv"}]}}},
        {"call_id": "T2", "phase": "completed", "tool": "get_run_method", "outcome": "error", "result": {"error": {"code": "INVALID_ARTIFACT", "remedy": "Rebuild the cache."}}},
    ]
    (agent_context.directory / "tool_calls.jsonl").write_text("\n".join(json.dumps(row) for row in records) + "\n")
    tab.on_answer("final [T1] and [T99]")
    rendered = tab.transcript.toPlainText()
    assert rendered.count("Agent\n") == 1
    assert "partial" not in rendered
    assert "final [T1] and [T99: invalid source]" in rendered
    assert "INVALID_ARTIFACT: Rebuild the cache." in tab.sources.toPlainText()
    assert "warning: failed cases included" in tab.sources.toPlainText()
    assert "facility" in tab.sources.toPlainText()
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


def test_unknown_citations_are_marked():
    assert cited_answer("120% [T1], claim [T999]", [{"call_id": "T1"}]) == "120% [T1], claim [T999: invalid source]"
    assert cited_answer("120% [Call\u202fT1]", [{"call_id": "T1"}]) == "120% [T1]"
