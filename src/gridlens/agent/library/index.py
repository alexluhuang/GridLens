"""The passage index: passages and their words, in SQLite.

`.gridlens-index/index.sqlite` holds, for every document GridLens has
read, keyed by the SHA-256 of its contents:

- `documents`: its title, page and passage counts, the number of words
  in each passage, and, for a file that could not be read, why not;
- `passages`: the page, page label, section, and text of each passage;
- `postings`: an inverted index of the passages' words. Each row says
  how often a word appears in one passage. The table is a B-tree keyed
  by (word, document, passage), so a search reads only the rows of the
  words it looks for;
- `files`: which file of the folder, by path, size, and modification
  time, holds which document.

BM25 scores are computed from the postings with the same formula and
constants as a scan of every passage would use, so they are the same
to the last bit. Only the indexer writes the index. Each document is
written in one transaction, and the database uses SQLite's write-ahead
log, so a search can read while the indexer writes, and sees all of a
document or none of it. The index holds the documents' text, so the
database is readable only by the user.
"""
from __future__ import annotations

from collections import Counter
import contextlib
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import sqlite3

import numpy as np

from gridlens.agent.library import cache
from gridlens.agent.library.reading import Passage


DATABASE = "index.sqlite"
# Changing the tables changes this, so an older index is rebuilt.
SCHEMA_VERSION = 1
BM25_K1 = 1.5
BM25_B = 0.75
BUSY_TIMEOUT_SECONDS = 30
_LENGTH_TYPE = np.dtype("<u4")
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*")
_TOKEN_PARTS = re.compile(r"[.\-/]")
_STOP_WORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or "
    "that the this to was were which with".split()
)
_SCHEMA = """
CREATE TABLE files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    pages INTEGER NOT NULL,
    passages INTEGER NOT NULL,
    lengths BLOB NOT NULL,
    error TEXT NOT NULL
);
CREATE TABLE passages (
    document INTEGER NOT NULL,
    passage INTEGER NOT NULL,
    page INTEGER,
    page_label TEXT NOT NULL,
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (document, passage)
);
CREATE TABLE postings (
    term TEXT NOT NULL,
    document INTEGER NOT NULL,
    passage INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (term, document, passage)
) WITHOUT ROWID;
"""


@dataclass(frozen=True)
class IndexedFile:
    """A file of the folder, by relative path, and its document."""

    path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class IndexedDocument:
    """A document in the index, and the word count of each passage.

    error is "" for a document that was read, and otherwise the
    sentence that says why it could not be.
    """

    key: int
    sha256: str
    title: str
    pages: int
    passages: int
    lengths: np.ndarray
    error: str


def tokens(text: str) -> list[str]:
    """Split text into lower-case search terms.

    Identifiers such as tpl-001-5.1 are kept whole and also split into
    their parts. Common English words are left out.
    """
    found = []
    for match in _TOKEN.finditer(text.lower()):
        term = match.group()
        if term in _STOP_WORDS:
            continue
        found.append(term)
        parts = _TOKEN_PARTS.split(term)
        if len(parts) > 1:
            found.extend(
                part for part in parts if part and part not in _STOP_WORDS
            )
    return found


def _passage_terms(passage: Passage) -> Counter:
    """Count the terms of a passage: its section, then its text."""
    return Counter(tokens(f"{passage.section}\n{passage.text}"))


def database_path(folder: Path) -> Path:
    """Return where the index of a Reference documents folder is."""
    return folder / cache.INDEX_FOLDER / DATABASE


def open_for_writing(folder: Path) -> sqlite3.Connection:
    """Open the index of a folder for the indexer; create it if needed.

    An index of another schema version, or a file that is not a
    database, is deleted and created again.
    """
    path = cache.index_folder(folder) / DATABASE
    try:
        connection = _connect_for_writing(path)
        version = _schema_version(connection)
    except sqlite3.DatabaseError:
        connection, version = None, -1
    if version not in (0, SCHEMA_VERSION):
        if connection is not None:
            connection.close()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        connection = _connect_for_writing(path)
        version = 0
    if version == 0:
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return connection


def _connect_for_writing(path: Path) -> sqlite3.Connection:
    """Open a private database in write-ahead log mode."""
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    os.close(os.open(path, flags, 0o600))
    connection = sqlite3.connect(
        path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None
    )
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def _schema_version(connection: sqlite3.Connection) -> int:
    """Return the schema version recorded in a database, 0 if none."""
    return connection.execute("PRAGMA user_version").fetchone()[0]


def open_for_reading(folder: Path) -> sqlite3.Connection | None:
    """Open the index of a folder for a search.

    Returns None when the folder has no index yet, or one the indexer
    will build again: of another schema version, or not a database.
    """
    path = database_path(folder)
    connection = None
    if path.is_file() and not path.is_symlink():
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=rw", uri=True,
            timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None,
        )
        try:
            current = _schema_version(connection) == SCHEMA_VERSION
        except sqlite3.DatabaseError:
            current = False
        if not current:
            connection.close()
            connection = None
    return connection


@contextlib.contextmanager
def _transaction(connection: sqlite3.Connection):
    """Run statements as one write transaction, locked at its start."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def add_document(
    connection: sqlite3.Connection, sha256: str, title: str, pages: int,
    passages: list[Passage],
) -> None:
    """Index a document's passages and their words, in one transaction.

    A document already in the index is left as it is.
    """
    counts = [_passage_terms(passage) for passage in passages]
    lengths = np.array([sum(count.values()) for count in counts],
                       dtype=_LENGTH_TYPE)
    with _transaction(connection):
        if _has_document(connection, sha256):
            return
        key = connection.execute(
            "INSERT INTO documents (sha256, title, pages, passages,"
            " lengths, error) VALUES (?, ?, ?, ?, ?, '')",
            (sha256, title, pages, len(passages), lengths.tobytes()),
        ).lastrowid
        connection.executemany(
            "INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?)",
            (
                (key, number, item.page, item.page_label, item.section,
                 item.text)
                for number, item in enumerate(passages)
            ),
        )
        connection.executemany(
            "INSERT INTO postings VALUES (?, ?, ?, ?)",
            (
                (term, key, number, count)
                for number, terms in enumerate(counts)
                for term, count in terms.items()
            ),
        )


def add_failure(
    connection: sqlite3.Connection, sha256: str, error: str
) -> None:
    """Record that a document could not be read, and why."""
    with _transaction(connection):
        if not _has_document(connection, sha256):
            connection.execute(
                "INSERT INTO documents (sha256, title, pages, passages,"
                " lengths, error) VALUES (?, '', 0, 0, ?, ?)",
                (sha256, b"", error),
            )


def _has_document(connection: sqlite3.Connection, sha256: str) -> bool:
    """Say whether the index holds a document, read or not."""
    found = connection.execute(
        "SELECT 1 FROM documents WHERE sha256 = ?", (sha256,)
    ).fetchone()
    return found is not None


def record_files(
    connection: sqlite3.Connection, files: list[IndexedFile]
) -> None:
    """Replace the record of which file holds which document."""
    with _transaction(connection):
        connection.execute("DELETE FROM files")
        connection.executemany(
            "INSERT INTO files VALUES (?, ?, ?, ?)",
            ((item.path, item.size, item.mtime_ns, item.sha256)
             for item in files),
        )


def remove_documents_except(
    connection: sqlite3.Connection, kept: set[str]
) -> int:
    """Remove every document whose SHA-256 is not in kept.

    Returns how many were removed. Removing a document reads the whole
    postings table once, so it is done for all of them together.
    """
    removed = [
        key for key, sha256 in connection.execute(
            "SELECT id, sha256 FROM documents"
        )
        if sha256 not in kept
    ]
    if removed:
        marks = ", ".join("?" * len(removed))
        with _transaction(connection):
            for table, column in (("postings", "document"),
                                  ("passages", "document"),
                                  ("documents", "id")):
                connection.execute(
                    f"DELETE FROM {table} WHERE {column} IN ({marks})",
                    removed,
                )
    return len(removed)


def read_files(connection: sqlite3.Connection) -> dict[str, IndexedFile]:
    """Return the recorded files of the folder, by relative path."""
    rows = connection.execute(
        "SELECT path, size, mtime_ns, sha256 FROM files"
    )
    return {row[0]: IndexedFile(*row) for row in rows}


def read_documents(
    connection: sqlite3.Connection,
) -> dict[str, IndexedDocument]:
    """Return every document in the index, by SHA-256."""
    rows = connection.execute(
        "SELECT id, sha256, title, pages, passages, lengths, error"
        " FROM documents"
    )
    return {
        sha256: IndexedDocument(
            key, sha256, title, pages, passages,
            np.frombuffer(lengths, dtype=_LENGTH_TYPE), error,
        )
        for key, sha256, title, pages, passages, lengths, error in rows
    }


def read_passages(
    connection: sqlite3.Connection, document: IndexedDocument, file: str,
    numbers: list[int] | None = None,
) -> list[Passage]:
    """Return passages of a document, as held by one of its files.

    numbers selects passages by their place in the document, in the
    order given; None returns them all, in order.
    """
    query = (
        "SELECT passage, page, page_label, section, text FROM passages"
        " WHERE document = ?"
    )
    arguments = [document.key]
    if numbers is not None:
        query += f" AND passage IN ({', '.join('?' * len(numbers))})"
        arguments += numbers
    found = {
        number: Passage(document.title, file, page, label, section, text)
        for number, page, label, section, text in connection.execute(
            query + " ORDER BY passage", arguments
        )
    }
    wanted = sorted(found) if numbers is None else numbers
    return [found[number] for number in wanted]


def bm25(
    connection: sqlite3.Connection, scope: list[IndexedDocument],
    query: str,
) -> np.ndarray:
    """Return the BM25 score of every passage of scope for query.

    The scores follow the passages of the documents in scope, in
    order; a document listed twice, for two files that hold it, counts
    twice, as two files would. The inverse document frequency, the
    number of passages, and their average length are those of scope.
    """
    total = sum(document.passages for document in scope)
    scores = np.zeros(total)
    wanted = list(dict.fromkeys(tokens(query)))
    if wanted and total:
        lengths = np.concatenate([document.lengths for document in scope])
        average = int(lengths.sum(dtype=np.int64)) / total or 1.0
        starts = _passage_starts(scope)
        for term in wanted:
            places, counts = _postings(connection, term, starts)
            if not places.size:
                continue
            inverse = math.log(
                1 + (total - places.size + 0.5) / (places.size + 0.5)
            )
            # The operations and their order are those of a scan of
            # every passage, so the scores match it exactly.
            length = lengths[places].astype(np.float64)
            scores[places] += (
                inverse * counts * (BM25_K1 + 1)
                / (counts + BM25_K1
                   * (1 - BM25_B + BM25_B * length / average))
            )
    return scores


def _passage_starts(scope: list[IndexedDocument]) -> dict[int, list[int]]:
    """Return where each document's passages start among scope's."""
    starts: dict[int, list[int]] = {}
    offset = 0
    for document in scope:
        starts.setdefault(document.key, []).append(offset)
        offset += document.passages
    return starts


def _postings(
    connection: sqlite3.Connection, term: str, starts: dict[int, list[int]]
) -> tuple[np.ndarray, np.ndarray]:
    """Return the places in scope of the passages that hold a term.

    Also returns how often each holds it, as floats.
    """
    marks = ", ".join("?" * len(starts))
    rows = connection.execute(
        "SELECT document, passage, count FROM postings"
        f" WHERE term = ? AND document IN ({marks})",
        (term, *starts),
    ).fetchall()
    places, counts = [], []
    for document, passage, count in rows:
        for start in starts[document]:
            places.append(start + passage)
            counts.append(count)
    return (np.array(places, dtype=np.int64),
            np.array(counts, dtype=np.float64))
