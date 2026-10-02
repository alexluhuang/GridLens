"""Bringing a folder's passage index up to date with its documents.

`update` indexes the passages and words of every new or changed file,
from the text cache when the file was read before, forgets the files
that are gone, and, when the local Ollama has an embedding model,
caches the vectors of every indexed document's passages.

A file is known by its path, size, and modification time. A file whose
size or time changed is hashed again, and one whose contents another
file already holds is not read again.

Reading is the slow part. PDFs are read in ranges of PDF_CHUNK_PAGES
pages by several processes at once, so even one long PDF is read on
several of the processor's cores. Each document is indexed, and can be
searched, as soon as its pages are read, and its vectors are cached as
soon as they are made. `update` reports its progress as it goes: the
stage ("checking", "reading", or "embedding"), how much of the stage
is done, of how much, and the file it is on.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
import contextlib
from dataclasses import dataclass
import functools
import multiprocessing
import os
from pathlib import Path
import sqlite3

from gridlens.agent.library import cache, index, reading, vectors
from gridlens.agent.policy import local_endpoint


PDF_CHUNK_PAGES = 40
# Cores left for the desktop and for GridPACK while PDFs are read.
SPARE_CORES = 2
# How long one range of pages may take before its PDF counts as
# unreadable.
CHUNK_TIMEOUT_SECONDS = 600

Progress = Callable[[str, int, int, str], None]


@dataclass(frozen=True)
class Summary:
    """What the index holds after an update."""

    documents: int
    passages: int
    unreadable: int


def _no_progress(stage: str, done: int, total: int, file: str) -> None:
    """Ignore a progress report."""


def update(
    folder: Path, endpoint: str = "", progress: Progress | None = None
) -> Summary:
    """Bring the index of a Reference documents folder up to date.

    endpoint is the local Ollama, whose embedding model, if it has one,
    embeds the passages; with endpoint "", nothing is embedded.
    progress, when given, is called with each step of the work.
    """
    report = progress or _no_progress
    files, __ = reading.document_files(folder)
    folder_index = cache.index_folder(folder)
    with contextlib.closing(index.open_for_writing(folder)) as connection:
        recorded = identify(folder, files, index.read_files(connection),
                            report)
        # The files are recorded first, so a search finds each new
        # document as soon as its passages are indexed.
        index.record_files(connection, recorded)
        index.remove_documents_except(
            connection, {item.sha256 for item in recorded}
        )
        known = set(index.read_documents(connection))
        new = distinct(recorded, known)
        for item, record in read_texts(folder, folder_index, new, report):
            index_file(connection, item, record)
        if endpoint:
            embed_documents(connection, folder_index, recorded, endpoint,
                            report)
        summary = _summary(connection, recorded)
    return summary


def _summary(
    connection: sqlite3.Connection, files: list[index.IndexedFile]
) -> Summary:
    """Count the documents of files the index holds, read or not."""
    documents = index.read_documents(connection)
    held = [documents[item.sha256] for item in files
            if item.sha256 in documents]
    readable = [document for document in held if not document.error]
    return Summary(
        len(readable), sum(document.passages for document in readable),
        len(held) - len(readable),
    )


def identify(
    folder: Path, files: list[Path], known: dict[str, index.IndexedFile],
    progress: Progress = _no_progress,
) -> list[index.IndexedFile]:
    """Return each file with the SHA-256 of its contents.

    A file recorded at its present size and modification time keeps
    its recorded SHA-256; any other file is hashed.
    """
    found = []
    for number, path in enumerate(files, start=1):
        relative = path.relative_to(folder).as_posix()
        progress("checking", number, len(files), relative)
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


def read_texts(
    folder: Path, folder_index: Path, items: list[index.IndexedFile],
    progress: Progress = _no_progress,
) -> Iterator[tuple[index.IndexedFile, dict]]:
    """Yield each file with its text record, as soon as it has one.

    Records already cached come first, then the files that are not
    PDFs, then the PDFs. Every record read from a file is cached.
    """
    unread = []
    for item in items:
        record = cache.load_text(folder_index, item.sha256)
        if record is None:
            unread.append(item)
        else:
            yield item, record
    pdfs = [item for item in unread if _is_pdf(item)]
    for item in unread:
        if not _is_pdf(item):
            record = read_text(folder / item.path)
            cache.save_text(folder_index, item.sha256, record)
            yield item, record
    for item, record in _read_pdfs(folder, pdfs, progress):
        cache.save_text(folder_index, item.sha256, record)
        yield item, record


def _is_pdf(item: index.IndexedFile) -> bool:
    """Say whether a file is a PDF, by its name."""
    return reading.SUFFIXES[Path(item.path).suffix.lower()] == "pdf"


def _read_pdfs(
    folder: Path, items: list[index.IndexedFile], progress: Progress
) -> Iterator[tuple[index.IndexedFile, dict]]:
    """Yield each PDF with its text record, read in parallel."""
    outlines = {}
    for item in items:
        try:
            outlines[item.sha256] = reading.pdf_outline(folder / item.path)
        except ValueError as exc:
            yield item, {"error": str(exc)}
    readable = [item for item in items if item.sha256 in outlines]
    ranges = {
        item.sha256: _page_ranges(len(outlines[item.sha256].labels))
        for item in readable
    }
    total = sum(len(outline.labels) for outline in outlines.values())
    workers = _worker_count(total,
                            sum(len(parts) for parts in ranges.values()))
    with _page_reader(workers) as read_pages:
        pending = [
            (item, [read_pages(folder / item.path, start, stop)
                    for start, stop in ranges[item.sha256]])
            for item in readable
        ]
        done = 0
        for item, parts in pending:
            outline = outlines[item.sha256]
            progress("reading", done, total, item.path)
            yield item, _gather(folder / item.path, outline, parts)
            done += len(outline.labels)
            progress("reading", done, total, item.path)


def _page_ranges(count: int) -> list[tuple[int, int]]:
    """Split a document's pages into ranges of PDF_CHUNK_PAGES pages."""
    return [(start, min(start + PDF_CHUNK_PAGES, count))
            for start in range(0, count, PDF_CHUNK_PAGES)]


def _worker_count(pages: int, ranges: int) -> int:
    """Return how many processes should read these pages, in ranges.

    Fewer pages than two ranges hold are read in this process, since
    starting processes would take longer than reading them.
    """
    cores = max(1, (os.cpu_count() or 1) - SPARE_CORES)
    return min(cores, ranges) if pages >= 2 * PDF_CHUNK_PAGES else 1


@contextlib.contextmanager
def _page_reader(workers: int):
    """Give a function that starts reading a range of PDF pages.

    The function returns a callable that waits for the range's text.
    With more than one worker, ranges are read by a pool of processes,
    which ends when the context does; otherwise they are read in this
    process, when they are waited for.
    """
    if workers < 2:
        yield _read_later
    else:
        context = multiprocessing.get_context("spawn")
        with context.Pool(workers) as pool:
            yield functools.partial(_start_reading, pool)


def _read_later(path: Path, start: int, stop: int) -> Callable:
    """Return a waiter that reads a range of pages in this process."""
    return functools.partial(reading.pdf_page_texts, path, start, stop)


def _start_reading(pool, path: Path, start: int, stop: int) -> Callable:
    """Start reading a range of pages in the pool; return its waiter."""
    started = pool.apply_async(reading.pdf_page_texts, (path, start, stop))
    return functools.partial(started.get, CHUNK_TIMEOUT_SECONDS)


def _gather(
    path: Path, outline: reading.PdfOutline, parts: list[Callable]
) -> dict:
    """Wait for a PDF's page ranges and return its text record."""
    texts = []
    try:
        for part in parts:
            texts.extend(part())
        title, pages = reading.assemble_pdf(path, outline, texts)
    except multiprocessing.TimeoutError:
        record = {"error": "it took too long to read; it may be damaged"}
    except ValueError as exc:
        record = {"error": str(exc)}
    else:
        record = {"title": title, "pages": pages}
    return record


def index_file(
    connection: sqlite3.Connection, item: index.IndexedFile, record: dict
) -> None:
    """Index the passages of a file's document, from its text record."""
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
    progress: Progress = _no_progress,
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
    unembedded = []
    for item in distinct(files):
        document = documents[item.sha256]
        path = vectors.vector_file(folder_index, item.sha256, model)
        needed = not document.error and document.passages > 0
        if needed and not vectors.vectors_ready(path, document.passages,
                                                dimensions):
            unembedded.append((item, document, path))
    total = sum(document.passages for __, document, __ in unembedded)
    done = 0
    for item, document, path in unembedded:
        passages = index.read_passages(connection, document, item.path)
        texts = [vectors.document_prompt(model, passage)
                 for passage in passages]
        progress("embedding", done, total, item.path)
        embedded = functools.partial(_embedding_progress, progress, done,
                                     total, item.path)
        vectors.save_vectors(path, vectors.embed(origin, model, texts,
                                                 embedded))
        done += document.passages


def _embedding_progress(
    progress: Progress, start: int, total: int, file: str, count: int
) -> None:
    """Report count more passages embedded, after start of total."""
    progress("embedding", start + count, total, file)
