"""The Clarke tab's row that shows the reference documents' indexing."""
from __future__ import annotations

import json
import os

from PySide6.QtWidgets import QApplication
import pytest

from gridlens.agent.library import cache, worker
from gridlens.gui.indexing import IndexingStatus


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def row(reference_library):
    """Return an indexing row for the reference library."""
    app = QApplication.instance() or QApplication([])
    shown = IndexingStatus(lambda: reference_library)
    yield shown
    shown.deleteLater()
    app.processEvents()


def write_status(folder, **status):
    """Write the indexer's status file, as a running indexer would."""
    path = cache.index_folder(folder) / worker.STATUS_FILE
    path.write_text(json.dumps(status), encoding="utf-8")


def test_the_row_shows_the_stage_and_progress_while_indexing(
    row, reference_library, monkeypatch
):
    monkeypatch.setattr(worker, "is_running", lambda folder: True)
    write_status(reference_library, state="indexing", stage="reading",
                 done=3, total=10, file="TPL-001-5.1.pdf")
    row.refresh()
    assert row.label.text() == (
        "Reference documents: reading 3 of 10 pages, TPL-001-5.1.pdf"
    )
    assert (row.progress.maximum(), row.progress.value()) == (10, 3)
    assert row.isVisibleTo(row.parentWidget() or row)
    assert not row.progress.isHidden()


def test_the_row_reports_what_the_index_holds_and_then_hides(
    row, reference_library
):
    write_status(reference_library, state="ready",
                 message="3 documents indexed, 4 passages")
    row.refresh()
    assert row.label.text() == (
        "Reference documents: 3 documents indexed, 4 passages"
    )
    assert row.progress.isHidden() and row.conceal.isActive()
    assert not row.poll.isActive()


def test_a_failed_indexing_stays_shown(row, reference_library):
    write_status(reference_library, state="failed", message="disk full")
    row.refresh()
    assert row.label.text() == (
        "Reference documents: the last indexing stopped: disk full"
    )
    assert not row.conceal.isActive()


def test_a_started_indexer_shows_as_starting_until_it_writes_a_status(
    row, reference_library, monkeypatch
):
    write_status(reference_library, state="ready", message="old result")
    monkeypatch.setattr(worker, "start", lambda folder, endpoint="": None)
    row.start("http://127.0.0.1:11434")
    assert row.label.text() == "Reference documents: starting"
    assert row.poll.isActive() and row.progress.maximum() == 0
    assert row.endpoint == "http://127.0.0.1:11434"


def test_indexing_starts_again_only_when_the_documents_change(
    row, reference_library, inline_indexer
):
    row.start()
    assert len(inline_indexer) == 1
    row.files_changed()
    assert len(inline_indexer) == 1
    (reference_library / "criteria/new.md").write_text("Rate C applies.")
    row.files_changed()
    assert len(inline_indexer) == 2


def test_the_row_watches_subfolders_but_not_the_index(row,
                                                      reference_library):
    cache.index_folder(reference_library)
    (reference_library / ".hidden").mkdir()
    row.watch()
    watched = set(row.watcher.directories())
    assert watched == {str(reference_library),
                       str(reference_library / "criteria")}
