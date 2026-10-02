"""The background indexer: a process keeping a folder's index current.

Indexing a folder of long documents can take minutes, longer than a
search should wait, and longer than the process that asks for it may
live: the runtime stops the GridLens MCP server at the end of every
turn. So `start` runs `gridlens --index-documents <folder>` as a
separate process, in its own session and at low priority, and returns
at once. The GUI starts it when a Clarke session starts, when the user
opens the folder, and when files arrive in it; a search starts it when
it finds files the index does not hold yet.

At most two indexers of a folder exist at a time: one running, and one
waiting for it to end. An indexer that finds another already waiting
leaves at once, since the waiting one's scan of the folder starts
after it was asked for. So every request is followed by a scan that
starts after it, and requests that arrive together share one.

The running indexer writes its progress to `.gridlens-index/status.json`
and its output, with any traceback, to `.gridlens-index/indexer.log`.
`is_running` and `read_status` are what a search and the GUI read.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

from gridlens.agent.library import cache, indexer
from gridlens.agent.process import gridlens_command
from gridlens.agent.session import timestamp


STATUS_FILE = "status.json"
LOG_FILE = "indexer.log"
RUN_LOCK = "indexer.lock"
WAIT_LOCK = "indexer-wait.lock"
MAX_LOG_BYTES = 1024 * 1024
NICENESS = 10
STATUS_INTERVAL_SECONDS = 0.5
STAGES = {
    "checking": "checking {done:,} of {total:,} files",
    "reading": "reading {done:,} of {total:,} pages",
    "embedding": "embedding {done:,} of {total:,} passages",
}


def start(folder: Path, endpoint: str = "") -> None:
    """Start an indexer of folder in the background, and return at once.

    endpoint is the local Ollama, whose embedding model embeds the
    passages; with endpoint "", nothing is embedded.
    """
    folder_index = cache.index_folder(folder)
    arguments = ["--index-documents", str(folder)]
    if endpoint:
        arguments += ["--endpoint", endpoint]
    log_path = folder_index / LOG_FILE
    if not is_running(folder) and _size(log_path) > MAX_LOG_BYTES:
        log_path.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    with os.fdopen(os.open(log_path, flags, 0o600), "ab") as log:
        subprocess.Popen(
            gridlens_command(*arguments), cwd=folder_index,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _size(path: Path) -> int:
    """Return a file's size, or 0 when it does not exist."""
    return path.stat().st_size if path.is_file() else 0


def is_running(folder: Path) -> bool:
    """Say whether an indexer of folder is running now."""
    handle = _try_lock(cache.index_folder(folder) / RUN_LOCK)
    if handle is not None:
        handle.close()
    return handle is None


def read_status(folder: Path) -> dict:
    """Return the latest status the folder's indexer wrote, or {}.

    The status has the state ("indexing", "ready", or "failed"), and,
    while indexing, the stage, how much of it is done of how much, and
    the file; when finished, a message. An indexer that was stopped
    before it finished leaves the state "indexing" while none runs.
    """
    path = cache.index_folder(folder) / STATUS_FILE
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = {}
    return status if isinstance(status, dict) else {}


def describe(status: dict, running: bool) -> str:
    """Say in a few words what the indexer is doing, or last did."""
    state = status.get("state", "")
    if running and status.get("stage") in STAGES:
        words = STAGES[status["stage"]].format(
            done=status.get("done", 0), total=status.get("total", 0)
        )
        found = f"{words}, {status['file']}" if status.get("file") else words
    elif running:
        found = "starting"
    elif state == "failed":
        found = f"the last indexing stopped: {status.get('message', '')}"
    elif state == "indexing":
        found = "the last indexing was stopped before it finished"
    else:
        found = status.get("message", "")
    return found


class _Status:
    """The running indexer's progress, as written to status.json."""

    def __init__(self, folder_index: Path) -> None:
        """Write the status of the indexer of this cache folder."""
        self.path = folder_index / STATUS_FILE
        self.written = 0.0

    def write(self, state: str, **details: object) -> None:
        """Replace the status with a state and its details, at once."""
        record = {"state": state, "pid": os.getpid(),
                  "updated_at": timestamp(), **details}
        data = json.dumps(record, ensure_ascii=False).encode("utf-8")
        cache.private_write(self.path, data)
        self.written = time.monotonic()

    def progress(self, stage: str, done: int, total: int, file: str) -> None:
        """Record progress, at most every STATUS_INTERVAL_SECONDS."""
        due = time.monotonic() - self.written >= STATUS_INTERVAL_SECONDS
        if due or done in (0, total):
            self.write("indexing", stage=stage, done=done, total=total,
                       file=file)


def _open_lock(path: Path):
    """Open a lock file, readable only by the user."""
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags, 0o600), "r+")


def _try_lock(path: Path):
    """Return a lock this process holds, or None if another holds it."""
    handle = _open_lock(path)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        handle = None
    return handle


def _wait_for_lock(path: Path):
    """Return a lock file this process holds, after waiting for it."""
    handle = _open_lock(path)
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def run(folder: Path, endpoint: str = "") -> bool:
    """Index folder after any running indexer, unless another waits.

    Returns whether this process indexed the folder. A failure is
    recorded in the status, then raised.
    """
    folder_index = cache.index_folder(folder)
    waiting = _try_lock(folder_index / WAIT_LOCK)
    if waiting is None:
        return False
    with waiting:
        running = _wait_for_lock(folder_index / RUN_LOCK)
    with running:
        status = _Status(folder_index)
        status.write("indexing", stage="", done=0, total=0, file="")
        try:
            summary = indexer.update(folder, endpoint, status.progress)
        except Exception as exc:
            status.write("failed", message=str(exc) or type(exc).__name__)
            raise
        status.write(
            "ready", documents=summary.documents, passages=summary.passages,
            message=(
                f"{summary.documents:,} documents indexed, "
                f"{summary.passages:,} passages"
            ),
        )
    return True


def main(argv: list[str]) -> int:
    """Run an indexer from the command line: `--index-documents`."""
    parser = argparse.ArgumentParser(
        prog="gridlens --index-documents",
        description="Index a folder of reference documents.",
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument("--endpoint", default="",
                        help="the local Ollama, to embed the passages")
    options = parser.parse_args(argv)
    if hasattr(os, "nice"):
        os.nice(NICENESS)
    try:
        run(options.folder.resolve(), options.endpoint)
    except Exception:
        traceback.print_exc()
        code = 1
    else:
        code = 0
    return code
