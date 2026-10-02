"""Bringing a folder's passage index up to date with its documents.

`update` indexes the passages and words of every new or changed file,
from the text cache when the file was read before, forgets the files
that are gone, and, when the local Ollama has an embedding model,
caches the vectors of every indexed document's passages.

A file is known by its path, size, and modification time. A file whose
size or time changed is hashed again, and one whose contents another
file already holds is not read again.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3

from gridlens.agent.library import cache, index, reading, vectors
from gridlens.agent.policy import local_endpoint


def update(folder: Path, endpoint: str = "") -> None:
    """Bring the index of a Reference documents folder up to date.

    endpoint is the local Ollama, whose embedding model, if it has one,
    embeds the passages; with endpoint "", nothing is embedded.
    """
    files, __ = reading.document_files(folder)
    folder_index = cache.index_folder(folder)
    with contextlib.closing(index.open_for_writing(folder)) as connection:
        recorded = identify(folder, files, index.read_files(connection))
        documents = index.read_documents(connection)
        for item in distinct(recorded, set(documents)):
            index_file(connection, folder_index, folder / item.path, item)
        index.record_files(connection, recorded)
        index.remove_documents_except(
            connection, {item.sha256 for item in recorded}
        )
        if endpoint:
            embed_documents(connection, folder_index, recorded, endpoint)


def identify(
    folder: Path, files: list[Path], known: dict[str, index.IndexedFile]
) -> list[index.IndexedFile]:
    """Return each file with the SHA-256 of its contents.

    A file recorded at its present size and modification time keeps
    its recorded SHA-256; any other file is hashed.
    """
    found = []
    for path in files:
        relative = path.relative_to(folder).as_posix()
        info = path.stat()
        before = known.get(relative)
        unchanged = before is not None and (
            (before.size, before.mtime_ns) == (info.st_size,
                                               info.st_mtime_ns)
        )
        sha256 = before.sha256 if unchanged else cache.file_sha256(path)
        found.append(index.IndexedFile(relative, info.st_size,
                                       info.st_mtime_ns, sha256))
    return found


def distinct(
    files: list[index.IndexedFile], known: set[str] | None = None
) -> list[index.IndexedFile]:
    """Return the first file of each SHA-256 that is not in known."""
    seen = set(known or ())
    first = []
    for item in files:
        if item.sha256 not in seen:
            seen.add(item.sha256)
            first.append(item)
    return first


def read_text(path: Path) -> dict:
    """Return a file's text record, as `cache.load_text` returns it."""
    try:
        title, pages = reading.extract(path)
    except ValueError as exc:
        record = {"error": str(exc)}
    else:
        record = {"title": title, "pages": pages}
    return record


def index_file(
    connection: sqlite3.Connection, folder_index: Path, path: Path,
    item: index.IndexedFile, record: dict | None = None,
) -> None:
    """Index the passages of one file's document.

    record is the file's text record when the caller has read it;
    otherwise it comes from the text cache, or from the file, which is
    then cached.
    """
    if record is None:
        record = cache.load_text(folder_index, item.sha256)
    if record is None:
        record = read_text(path)
        cache.save_text(folder_index, item.sha256, record)
    if "error" in record:
        index.add_failure(connection, item.sha256, record["error"])
    else:
        pages = [(page, label, text) for page, label, text in record["pages"]]
        passages = reading.split_passages(record["title"], item.path, pages)
        numbered = sum(1 for page, __, __ in pages if page is not None)
        index.add_document(connection, item.sha256, record["title"],
                           numbered, passages)


def embed_documents(
    connection: sqlite3.Connection, folder_index: Path,
    files: list[index.IndexedFile], endpoint: str,
) -> None:
    """Cache the vectors of every indexed document not embedded yet.

    Nothing is embedded when the local Ollama has no embedding model.
    A cached matrix of another width than the model's vectors now is
    embedded again.
    """
    origin = local_endpoint(endpoint)
    model = vectors.embedding_model(origin)
    if not model:
        return
    dimensions = vectors.model_dimensions(origin, model)
    documents = index.read_documents(connection)
    for item in distinct(files):
        document = documents[item.sha256]
        path = vectors.vector_file(folder_index, item.sha256, model)
        if document.error or not document.passages:
            continue
        if vectors.vectors_ready(path, document.passages, dimensions):
            continue
        passages = index.read_passages(connection, document, item.path)
        texts = [vectors.document_prompt(model, passage)
                 for passage in passages]
        vectors.save_vectors(path, vectors.embed(origin, model, texts))
