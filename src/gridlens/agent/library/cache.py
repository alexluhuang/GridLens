"""The cache of a Reference documents folder, in its .gridlens-index/.

Everything GridLens derives from the documents in a folder lives in
the folder's `.gridlens-index/`. The text of each file is cached
there, keyed by the file's SHA-256, so a file is read again only when
it changes. The cache holds the documents' text, so its files are
readable only by the user, and each is written in one step, so a
reader never sees half a file.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
from pathlib import Path

from gridlens.agent.policy import AgentError


INDEX_FOLDER = ".gridlens-index"
# Changing how text is extracted or split changes this, so every
# cached file is read again.
INDEX_VERSION = "2026.09.30"
_HASH_BLOCK_BYTES = 1 << 20


def index_folder(folder: Path) -> Path:
    """Return the cache folder of a Reference documents folder.

    The cache folder is created, readable only by the user, when it
    does not exist. Raises AgentError when it is a symbolic link.
    """
    index = folder / INDEX_FOLDER
    if index.is_symlink():
        raise AgentError(
            "UNSAFE_PATH",
            f"{index} is a symbolic link; remove it so GridLens can "
            "write its cache there.",
        )
    index.mkdir(mode=0o700, exist_ok=True)
    return index


def private_write(path: Path, data: bytes) -> None:
    """Write a cache file in one step, readable only by the user."""
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(temporary, flags, 0o600), "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of a file's contents, in hexadecimal."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        read_block = functools.partial(handle.read, _HASH_BLOCK_BYTES)
        for block in iter(read_block, b""):
            digest.update(block)
    return digest.hexdigest()


def load_text(index: Path, sha256: str) -> dict | None:
    """Return the cached text of a file, or None when none is cached.

    The record is {"title": title, "pages": [[page, label, text],
    ...]}, or {"error": sentence} for a file that could not be read.
    A cache file that is not valid JSON counts as missing.
    """
    path = index / f"{sha256}.json"
    record = None
    if path.is_file():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            record = None
    return record


def save_text(index: Path, sha256: str, record: dict) -> None:
    """Cache the text record of a file, as `load_text` returns it."""
    data = json.dumps(record, ensure_ascii=False).encode("utf-8")
    private_write(index / f"{sha256}.json", data)
