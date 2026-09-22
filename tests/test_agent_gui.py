from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gridlens.agent.runtime import RuntimeStatus
from gridlens.core.project import Project
from gridlens.gui.agent_tab import AgentTab, cited_answer


def test_agent_tab_scope_plain_text_and_disabled_hosted_models(agent_project):
    app = QApplication.instance() or QApplication([])
    tab = AgentTab()
    tab.set_project(Project("Synthetic Project", agent_project))
    assert tab.run_combo.count() == 2
    assert not tab.runtime_combo.model().item(1).isEnabled()
    assert not tab.runtime_combo.model().item(2).isEnabled()
    tab.on_probed(RuntimeStatus(True, "Local", "/bin/hermes", "0.21.4", "http://127.0.0.1:11434", ("test:model",)))
    tab.input.setPlainText("Where are files?")
    assert tab.send_button.isEnabled()
    tab.transcript.setPlainText('<img src="https://remote.invalid/data"> [T999]')
    assert '<img src="https://remote.invalid/data">' in tab.transcript.toPlainText()
    tab.new_session()
    assert not tab.transcript.toPlainText()
    assert tab.shutdown()
    tab.deleteLater()
    app.processEvents()


def test_unknown_citations_are_marked():
    assert cited_answer("120% [T1], claim [T999]", [{"call_id": "T1"}]) == "120% [T1], claim [T999: invalid source]"
    assert cited_answer("120% [Call\u202fT1]", [{"call_id": "T1"}]) == "120% [T1]"
