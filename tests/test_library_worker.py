"""The background indexer process and the status it writes."""
from __future__ import annotations

import fcntl
import os
import subprocess
import threading
import time

import pytest

from gridlens.agent.library import cache, indexer, worker


def hold_lock(folder, name):
    """Take one of the indexer's locks of folder, as another process."""
    handle = (cache.index_folder(folder) / name).open("a")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def test_an_indexer_indexes_the_folder_and_reports_it_ready(
    reference_library
):
    assert worker.run(reference_library) is True
    status = worker.read_status(reference_library)
    assert (status["state"], status["documents"], status["passages"]) == (
        "ready", 3, 4
    )
    assert status["message"] == "3 documents indexed, 4 passages"
    assert status["pid"] == os.getpid()
    assert worker.is_running(reference_library) is False


def test_an_indexer_leaves_at_once_when_another_already_waits(
    reference_library
):
    with hold_lock(reference_library, worker.WAIT_LOCK):
        assert worker.run(reference_library) is False
    assert worker.read_status(reference_library) == {}


def test_an_indexer_waits_for_the_running_one_to_end(reference_library):
    outcome = []
    with hold_lock(reference_library, worker.RUN_LOCK):
        waiting = threading.Thread(
            target=lambda: outcome.append(worker.run(reference_library))
        )
        waiting.start()
        time.sleep(0.2)
        assert waiting.is_alive() and worker.is_running(reference_library)
    waiting.join(10)
    assert outcome == [True]
    assert worker.read_status(reference_library)["state"] == "ready"


def test_a_failure_is_recorded_in_the_status_and_raised(reference_library,
                                                        monkeypatch):
    def broken(folder, endpoint="", progress=None):
        progress("reading", 3, 10, "TPL-001-5.1.pdf")
        raise OSError("No space left on device")

    monkeypatch.setattr(indexer, "update", broken)
    with pytest.raises(OSError):
        worker.run(reference_library)
    status = worker.read_status(reference_library)
    assert (status["state"], status["message"]) == (
        "failed", "No space left on device"
    )


def test_progress_is_written_at_the_start_and_end_of_each_stage(
    reference_library, monkeypatch
):
    written = []

    def update(folder, endpoint="", progress=None):
        for done in range(0, 11):
            progress("reading", done, 10, "TPL-001-5.1.pdf")
            written.append(worker.read_status(folder))
        return indexer.Summary(1, 2, 0)

    monkeypatch.setattr(worker, "STATUS_INTERVAL_SECONDS", 3600)
    monkeypatch.setattr(indexer, "update", update)
    worker.run(reference_library)
    done = [status["done"] for status in written]
    assert done[0] == 0 and done[-1] == 10 and set(done) == {0, 10}


def test_the_status_says_what_the_indexer_is_doing_or_last_did():
    reading = {"state": "indexing", "stage": "reading", "done": 1200,
               "total": 5000, "file": "TPL.pdf"}
    assert worker.describe(reading, True) == (
        "reading 1,200 of 5,000 pages, TPL.pdf"
    )
    assert worker.describe({"state": "indexing"}, True) == "starting"
    assert worker.describe(reading, False) == (
        "the last indexing was stopped before it finished"
    )
    failed = {"state": "failed", "message": "Ollama is not running"}
    assert worker.describe(failed, False) == (
        "the last indexing stopped: Ollama is not running"
    )
    ready = {"state": "ready", "message": "3 documents indexed, 4 passages"}
    assert worker.describe(ready, False) == ready["message"]


def test_start_runs_a_detached_low_priority_gridlens_indexer(
    reference_library, inline_indexer, monkeypatch
):
    launched = []

    def popen(argv, **options):
        launched.append((argv, options))

    monkeypatch.setattr(subprocess, "Popen", popen)
    inline_indexer.original(reference_library, "http://127.0.0.1:11434")
    ((argv, options),) = launched
    assert argv[-4:] == ["--index-documents", str(reference_library),
                         "--endpoint", "http://127.0.0.1:11434"]
    assert options["start_new_session"] is True
    assert options["cwd"] == reference_library / cache.INDEX_FOLDER
    log = reference_library / cache.INDEX_FOLDER / worker.LOG_FILE
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_the_command_lowers_its_priority_and_reports_a_failure(
    reference_library, monkeypatch, capsys
):
    niceness = []
    monkeypatch.setattr(os, "nice", niceness.append)
    assert worker.main([str(reference_library)]) == 0
    assert niceness == [worker.NICENESS]

    def broken(folder, endpoint=""):
        raise RuntimeError("index damaged")

    monkeypatch.setattr(worker, "run", broken)
    assert worker.main([str(reference_library)]) == 1
    assert "RuntimeError: index damaged" in capsys.readouterr().err
