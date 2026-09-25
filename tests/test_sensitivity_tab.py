from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from gridlens.core.app_settings import AppSettings  # noqa: E402
from gridlens.gui import run_tab, sensitivity_tab  # noqa: E402
from gridlens.gui.sensitivity_tab import SensitivityTab  # noqa: E402
from gridlens.psse import layouts, parse, patch  # noqa: E402


def open_tab(three_bus_project, kind: str = "generator") -> SensitivityTab:
    """Return a tab showing one kind of record of the three-bus project."""
    QApplication.instance() or QApplication([])
    tab = SensitivityTab()
    tab.set_project(*three_bus_project)
    tab.load_case()
    tab.kind.setCurrentIndex(layouts.KINDS.index(kind))
    return tab


def cell(tab: SensitivityTab, row: int, name: str):
    """Return the index of a field's cell in a row of the shown table."""
    table = tab.view.model()
    column = table.names + layouts.names(33, table.kind).index(name)
    return table.index(row, column)


def test_the_tab_shows_every_field_of_the_chosen_records(three_bus_project):
    tab = open_tab(three_bus_project)
    table = tab.view.model()

    headers = [table.headerData(column, Qt.Horizontal)
               for column in range(table.columnCount())]
    assert headers == ["Bus name", *layouts.names(33, "generator")]
    assert table.rowCount() == 2
    assert table.data(table.index(0, 0)) == "NORTH 1"
    assert table.data(cell(tab, 1, "PT")) == "200.000"
    assert "version 33" in tab.case_label.text()
    assert tab.run_button.isEnabled()


def test_a_field_the_file_leaves_out_shows_the_psse_value_in_grey(
        three_bus_project):
    """The fixture's generators end at F1, so WMOD is assumed."""
    tab = open_tab(three_bus_project)
    table = tab.view.model()

    assert table.data(cell(tab, 0, "WMOD")) == "0"
    assert table.data(cell(tab, 0, "WMOD"), Qt.ForegroundRole) == (
        sensitivity_tab.ASSUMED)
    assert table.data(cell(tab, 0, "PG"), Qt.ForegroundRole) is None


def test_editing_a_cell_marks_it_and_becomes_an_edit(three_bus_project):
    tab = open_tab(three_bus_project)
    table = tab.view.model()

    assert table.setData(cell(tab, 0, "PG"), " 55 ")

    line = table.row(0).line
    assert tab.edits() == [patch.Edit("generator", line, {"PG": "55"})]
    assert table.data(cell(tab, 0, "PG"), Qt.BackgroundRole) == (
        sensitivity_tab.CHANGED)
    assert table.data(cell(tab, 0, "PG"), Qt.ToolTipRole) == "Was 40.000"
    assert "0 added, 1 changed, 0 removed" in tab.status.text()


def test_an_invalid_value_is_refused_with_its_reason(three_bus_project):
    tab = open_tab(three_bus_project)

    assert not tab.view.model().setData(cell(tab, 0, "STAT"), "on")

    assert tab.status.text() == "STAT must be a whole number."
    assert tab.edits() == []


def test_rows_can_be_added_removed_and_restored(three_bus_project):
    tab = open_tab(three_bus_project, "load")
    table = tab.view.model()

    table.add([201])
    table.toggle_removed([0])

    kinds = [(edit.line is None, edit.removed) for edit in tab.edits()]
    assert kinds == [(False, True), (True, False)]
    assert table.data(table.index(1, 1), Qt.BackgroundRole) == (
        sensitivity_tab.ADDED)
    assert not table.flags(table.index(0, 1)) & Qt.ItemIsEditable
    table.toggle_removed([0, 1])
    assert tab.edits() == []


def test_the_filter_matches_bus_numbers_ids_and_bus_names(three_bus_project):
    tab = open_tab(three_bus_project, "branch")
    table = tab.view.model()

    tab.filter.setText("201")
    assert [table.row(0).values[:2]] == [["102", "201"]]
    tab.filter.setText("north 2")
    assert table.rowCount() == 2
    tab.filter.setText("south 101")
    assert table.rowCount() == 0
    table.add([101, 201])
    assert table.rowCount() == 1  # A new row shows whatever the filter.


def test_edits_are_kept_while_the_project_case_is_unchanged(
        three_bus_project):
    tab = open_tab(three_bus_project)
    tab.view.model().setData(cell(tab, 0, "PG"), "55")

    tab.set_project(*three_bus_project)
    tab.load_case()

    assert len(tab.edits()) == 1


def test_a_case_gridlens_cannot_edit_is_explained(three_bus_project):
    project, project_data = three_bus_project
    base = project.original_inputs_dir / "three_bus_v33.raw"
    base.write_text(base.read_text().replace(" 33, 0, 0,", " 30, 0, 0,", 1))

    tab = open_tab(three_bus_project)

    assert "cannot be edited" in tab.case_label.text()
    assert "versions 33, 34, and 35" in tab.case_label.text()
    assert not tab.run_button.isEnabled()


def test_run_hands_the_edited_case_to_the_run_tab(
        tmp_path, monkeypatch, three_bus_project):
    """The Run tab writes the edited case and an XML naming it, and runs."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(run_tab, "RunWorker", FakeWorker)
    monkeypatch.setattr(FakeWorker, "started", [])
    runs = run_tab.RunTab(AppSettings())
    runs.set_project(*three_bus_project)
    tab = open_tab(three_bus_project)
    tab.run_requested.connect(runs.start_sensitivity_run)
    tab.view.model().setData(cell(tab, 0, "PG"), "55")

    tab.run_case()

    request = FakeWorker.started[-1]
    assert request.xml_filename == "input_sensitivity.xml"
    edited = request.run_dir / "work" / "three_bus_v33_sensitivity.raw"
    assert parse.read_case(edited).records["generator"][0].values[2] == "55"
    assert "1 changed" in request.notes


def test_run_without_edits_says_so_and_runs_nothing(
        monkeypatch, three_bus_project):
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args: shown.append(args[2]))
    tab = open_tab(three_bus_project)
    requested = []
    tab.run_requested.connect(requested.append)

    tab.run_case()

    assert requested == []
    assert shown == ["Edit, add, or remove a record first."]


class FakeWorker(QObject):
    """Stands in for RunTab's worker, recording the requests it would run."""

    log_line = Signal(str)
    progress = Signal(object)
    finished_run = Signal(object)
    failed_run = Signal(str)
    started = []

    def __init__(self, request) -> None:
        super().__init__()
        self.request = request

    def start(self) -> None:
        FakeWorker.started.append(self.request)

    def isRunning(self) -> bool:  # noqa: N802 - Qt naming
        return False
