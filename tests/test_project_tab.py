"""The Project tab adopts an attached GridPACK configuration and asks before one input replaces another."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from gridlens.core.app_settings import AppSettings
from gridlens.gui.project_tab import ProjectTab


CONFIGURATION = "<Configuration><Powerflow><networkConfiguration>case.raw</networkConfiguration></Powerflow></Configuration>"


def test_attached_configuration_is_used_and_same_name_inputs_ask(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    attached = tmp_path / "attached"
    attached.mkdir()
    (attached / "case.raw").write_text("raw")
    (attached / "input.xml").write_text(CONFIGURATION)
    tab = ProjectTab(AppSettings(default_projects_dir=tmp_path / "projects"))
    tab.project_name.setText("Attached Study")
    tab.project_dir.setText(str(tmp_path / "projects/Attached_Study"))
    emitted = []
    tab.project_changed.connect(lambda project, data: emitted.append((project, data)))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([str(attached / "case.raw"), str(attached / "input.xml")], ""))
    tab.add_files()
    assert "GridPACK configuration" in tab.file_list.item(1).text()
    tab.save_project()
    project, data = emitted[-1]
    assert data.xml_file_name == "input.xml"
    assert "GridPACK configuration: input.xml" in tab.status.text()
    tab.set_project(project, data)  # as MainWindow does for every tab

    # A file named like a saved input is added only when the user agrees to replace it.
    other = tmp_path / "other"
    other.mkdir()
    (other / "input.xml").write_text(CONFIGURATION.replace("case.raw", "other.raw"))
    (other / "monitor.csv").write_text("1,2")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([str(other / "input.xml"), str(other / "monitor.csv")], ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    tab.add_files()
    assert [path.name for path in tab.input_paths] == ["case.raw", "input.xml", "monitor.csv"]
    assert tab.input_paths[1] == project.original_inputs_dir / "input.xml"
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    tab.add_files()
    assert tab.input_paths[1] == (other / "input.xml").resolve()

    # Showing the project again, as after the Configuration tab saves, keeps files not saved yet.
    tab.set_project(project, data)
    assert [path.name for path in tab.input_paths] == ["case.raw", "input.xml", "monitor.csv"]
    assert tab.input_paths[2] == (other / "monitor.csv").resolve()
    tab.deleteLater()
    app.processEvents()
