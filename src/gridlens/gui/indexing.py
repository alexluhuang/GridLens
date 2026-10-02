"""A row in the Clarke tab that shows the reference documents' indexing.

The row starts the background indexer (`gridlens.agent.library.worker`)
when asked to, and when files arrive in the Reference documents folder,
which it watches with its subfolders. While an indexer runs, the row
reads its status once a second and shows the stage and how far it has
got; when the indexer ends, the row says what the index holds, then
hides. A failure, or an indexer stopped before it finished, stays
shown until the next indexing.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar

from gridlens.agent.library import cache, reading, worker
from gridlens.agent.policy import DEFAULT_ENDPOINT


POLL_MILLISECONDS = 1000
# Files being copied in change for a while; indexing starts once the
# folder has been still this long.
SETTLE_MILLISECONDS = 2000
SHOW_RESULT_MILLISECONDS = 8000
# How many polls a started indexer has to show that it runs, before the
# row reports the status it finds.
START_POLLS = 5


def documents_signature(folder: Path) -> tuple:
    """Return what identifies the folder's documents now.

    The signature holds each document's path, size, and modification
    time, so it changes when a document is added, removed, or changed.
    """
    files = reading.document_files(folder)[0] if folder.is_dir() else []
    signature = []
    for path in files:
        info = path.stat()
        signature.append((path.relative_to(folder).as_posix(), info.st_size,
                          info.st_mtime_ns))
    return tuple(signature)


class IndexingStatus(QFrame):
    """The indexing of the reference documents, shown and started."""

    def __init__(self, folder: Callable[[], Path], parent=None) -> None:
        """Show the indexing of the folder that folder() returns."""
        super().__init__(parent)
        self.setObjectName("agentIndexStatus")
        self.folder = folder
        self.endpoint = DEFAULT_ENDPOINT
        self.signature: tuple | None = None
        self.before: dict = {}
        self.start_polls = 0
        self.label = QLabel()
        self.label.setTextFormat(Qt.PlainText)
        self.label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(220)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.progress)
        self.poll = QTimer(self)
        self.poll.setInterval(POLL_MILLISECONDS)
        self.poll.timeout.connect(self.refresh)
        self.settle = QTimer(self)
        self.settle.setSingleShot(True)
        self.settle.setInterval(SETTLE_MILLISECONDS)
        self.settle.timeout.connect(self.files_changed)
        self.conceal = QTimer(self)
        self.conceal.setSingleShot(True)
        self.conceal.setInterval(SHOW_RESULT_MILLISECONDS)
        self.conceal.timeout.connect(self.hide)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.folder_changed)
        self.hide()
        self.watch()

    def start(self, endpoint: str = "") -> None:
        """Index the folder in the background and show the progress.

        endpoint is the local Ollama whose embedding model embeds the
        passages; "" keeps the one used before.
        """
        self.endpoint = endpoint or self.endpoint
        folder = self.folder()
        folder.mkdir(parents=True, exist_ok=True)
        self.signature = documents_signature(folder)
        self.before = worker.read_status(folder)
        self.start_polls = START_POLLS
        worker.start(folder, self.endpoint)
        self.watch()
        self.poll.start()
        self.refresh()

    def watch(self) -> None:
        """Watch the folder and every subfolder but the cache's."""
        folder = self.folder()
        if folder.is_dir():
            folders = [folder] + [
                path for path in folder.rglob("*")
                if path.is_dir() and not _hidden(folder, path)
            ]
            watched = set(self.watcher.directories())
            new = [str(path) for path in folders if str(path) not in watched]
            if new:
                self.watcher.addPaths(new)

    def folder_changed(self, path: str) -> None:
        """Wait for the folder to be still, then look at it again."""
        self.settle.start()

    def files_changed(self) -> None:
        """Index again if the folder's documents changed."""
        if documents_signature(self.folder()) != self.signature:
            self.start()
        else:
            self.watch()

    def refresh(self) -> None:
        """Show what the indexer is doing now, or what it last did."""
        folder = self.folder()
        running = worker.is_running(folder)
        status = worker.read_status(folder)
        # An indexer just started may not have written its status yet.
        starting = (not running and status == self.before
                    and self.start_polls > 0)
        self.start_polls = max(0, self.start_polls - 1)
        described = worker.describe(status, running or starting)
        self.label.setText(f"Reference documents: {described}")
        self.progress.setVisible(running or starting)
        if running:
            total = int(status.get("total") or 0)
            self.progress.setRange(0, total)
            self.progress.setValue(min(int(status.get("done") or 0), total))
        elif starting:
            self.progress.setRange(0, 0)
        else:
            self.poll.stop()
            if status.get("state") == "ready":
                self.conceal.start()
        if running or starting:
            self.conceal.stop()
        self.show()


def _hidden(folder: Path, path: Path) -> bool:
    """Say whether a subfolder is hidden or is the index's own."""
    parts = path.relative_to(folder).parts
    return cache.INDEX_FOLDER in parts or any(
        part.startswith(".") for part in parts
    )
