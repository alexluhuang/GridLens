"""Searching the reference library: which documents, and which passages.

A search reads the passage index; it never reads a document itself. A
file of the folder is searched once the index holds its passages, as
of its current size and modification time, and, when the local Ollama
has an embedding model, once its passages' vectors are cached too.
Every other file is pending: the search names it, and leaves it out.

Passages are scored with BM25, which rewards exact terms such as
"TPL-001" or "Rate B". With an embedding model, the score also counts
how close each passage's meaning is to the query: the BM25 scores and
the similarities are each scaled to 0 to 1 over the passages searched,
and averaged. Passages with equal scores keep the folder's order.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

import numpy as np

from gridlens.agent.library import cache, index, reading, vectors
from gridlens.agent.policy import AgentError, local_endpoint


HYBRID_WEIGHT = 0.5
BM25_ONLY = "BM25 (no local embedding model is installed in Ollama)"


@dataclass(frozen=True)
class Document:
    """A file of the folder, by its path as cited, and its document."""

    file: str
    path: Path
    indexed: index.IndexedDocument


@dataclass(frozen=True)
class Catalog:
    """What a search can read in a folder, and what it cannot yet.

    documents are searchable now, in the folder's order; pending names
    the files still to index or embed; problems has a sentence for each
    file left out; model is the embedding model whose vectors the
    search uses, or "".
    """

    folder: Path
    documents: list[Document]
    pending: list[str]
    problems: list[str]
    model: str


@dataclass(frozen=True)
class Match:
    """A ranked passage: its document, its place there, its scores."""

    document: Document
    passage: int
    score: float
    bm25: float
    similarity: float | None


@dataclass(frozen=True)
class Result:
    """A search's documents, its best passages, and how it scored them.

    searched are the documents the search covered; matches are the
    best of total ranked passages, with their passages' text in
    passages; retrieval describes the scoring.
    """

    catalog: Catalog
    searched: list[Document]
    matches: list[Match]
    passages: list[reading.Passage]
    total: int
    retrieval: str


def read_catalog(
    folder: Path, connection: sqlite3.Connection | None, model: str = "",
    dimensions: int = 0,
) -> Catalog:
    """Return which files of a folder a search can read now.

    connection is the open index, or None when the folder has none.
    With model, a document is ready only once its vectors from that
    model are cached, dimensions wide when dimensions is not 0.
    """
    files, problems = reading.document_files(folder)
    known = index.read_files(connection) if connection else {}
    documents = index.read_documents(connection) if connection else {}
    folder_index = folder / cache.INDEX_FOLDER
    ready, pending = [], []
    for path in files:
        relative = path.relative_to(folder).as_posix()
        document = _current_document(path, known.get(relative), documents)
        if document is None:
            pending.append(relative)
        elif document.error:
            problems.append(f"{relative}: {document.error}.")
        elif _embedded(folder_index, document, model, dimensions):
            ready.append(Document(relative, path, document))
        else:
            pending.append(relative)
    return Catalog(folder, ready, pending, problems, model)


def _embedded(
    folder_index: Path, document: index.IndexedDocument, model: str,
    dimensions: int,
) -> bool:
    """Say whether a document's vectors are cached, if it needs them.

    Without a model, or for a document with no passages, none are
    needed.
    """
    needed = bool(model) and document.passages > 0
    return not needed or vectors.vectors_ready(
        vectors.vector_file(folder_index, document.sha256, model),
        document.passages, dimensions,
    )


def _current_document(
    path: Path, recorded: index.IndexedFile | None,
    documents: dict[str, index.IndexedDocument],
) -> index.IndexedDocument | None:
    """Return a file's document, if the index is of its contents.

    The index is current for a file when it recorded the file at its
    present size and modification time.
    """
    info = path.stat()
    current = recorded is not None and (
        (recorded.size, recorded.mtime_ns) == (info.st_size,
                                               info.st_mtime_ns)
    )
    return documents.get(recorded.sha256) if current else None


def in_scope(documents: list[Document], wanted: str) -> list[Document]:
    """Keep the documents whose file name or title contains wanted."""
    key = wanted.strip().casefold()
    return [
        item for item in documents
        if not key or key in item.file.casefold()
        or key in item.indexed.title.casefold()
    ]


def find(
    folder: Path, query: str, endpoint: str = "", document: str = "",
    limit: int = 5,
) -> Result:
    """Search a folder's indexed documents for query.

    endpoint is the local Ollama, whose embedding model, if any, adds
    similarity to the scores. document limits the search to files
    whose name or title contains it. limit is how many of the best
    passages to return with their text (0 returns all). With query
    blank, nothing is ranked and the result lists the documents.
    """
    model, query_vector = "", None
    if endpoint and query.strip():
        model, query_vector = _query_embedding(endpoint, query)
    dimensions = query_vector.size if query_vector is not None else 0
    connection = index.open_for_reading(folder)
    try:
        catalog = read_catalog(folder, connection, model, dimensions)
        searched = in_scope(catalog.documents, document)
        matches, total, retrieval = [], 0, BM25_ONLY
        if query.strip() and connection is not None and searched:
            matches, total, retrieval = _rank(
                connection, folder, searched, query, query_vector, limit,
                model,
            )
        passages = _read_matches(connection, matches)
    finally:
        if connection is not None:
            connection.close()
    return Result(catalog, searched, matches, passages, total, retrieval)


def _query_embedding(
    endpoint: str, query: str
) -> tuple[str, np.ndarray | None]:
    """Return the embedding model and the query's vector, if any.

    Without a loopback endpoint or an embedding model, there is none.
    """
    try:
        origin = local_endpoint(endpoint)
    except AgentError:
        origin = ""
    model = vectors.embedding_model(origin) if origin else ""
    query_vector = None
    if model:
        query_vector = vectors.query_vector(origin, model, query)
    return model, query_vector


def _rank(
    connection: sqlite3.Connection, folder: Path, searched: list[Document],
    query: str, query_vector: np.ndarray | None, limit: int, model: str,
) -> tuple[list[Match], int, str]:
    """Rank every passage of the searched documents for query.

    Returns the best limit matches (0 returns all), how many passages
    were ranked, and a description of the scoring. Without a query
    vector, only passages that hold a query term are ranked.
    """
    lexical = index.bm25(connection, [item.indexed for item in searched],
                         query)
    if query_vector is None:
        places = np.flatnonzero(lexical > 0)
        order = places[np.argsort(-lexical[places], kind="stable")]
        score, similarity = lexical, None
        retrieval = BM25_ONLY
    else:
        similarity = _similarity(folder, searched, model,
                                 query_vector)
        score = _hybrid(lexical, similarity)
        order = np.argsort(-score, kind="stable")
        plain = vectors.embedding_prompts(model) == vectors.PLAIN_PROMPTS
        prompted = (
            "as plain text" if plain
            else "in the model's retrieval prompt format"
        )
        retrieval = (
            f"BM25 and {model} embeddings (query and passages {prompted}),"
            " each scaled to 0 to 1 over the passages searched, averaged"
        )
    shown = order[:limit] if limit else order
    owners = np.repeat(np.arange(len(searched)),
                       [item.indexed.passages for item in searched])
    starts = np.cumsum([0] + [item.indexed.passages for item in searched])
    matches = [
        Match(
            searched[owners[place]], int(place - starts[owners[place]]),
            float(score[place]), float(lexical[place]),
            None if similarity is None else float(similarity[place]),
        )
        for place in shown
    ]
    return matches, int(order.size), retrieval


def _similarity(
    folder: Path, searched: list[Document], model: str,
    query_vector: np.ndarray,
) -> np.ndarray:
    """Return how close each searched passage is to the query vector.

    Each document's matrix is compared on its own, in one
    matrix-vector product, so its similarities do not depend on the
    other documents searched.
    """
    folder_index = folder / cache.INDEX_FOLDER
    products = [np.zeros(0, dtype=np.float32)]
    for item in searched:
        if not item.indexed.passages:
            continue
        path = vectors.vector_file(folder_index, item.indexed.sha256, model)
        matrix = vectors.load_vectors(path, item.indexed.passages,
                                      query_vector.size)
        if matrix is None:
            raise AgentError(
                "INDEX_CHANGED",
                "The reference documents changed during the search; "
                "search again.",
            )
        products.append(matrix @ query_vector)
    return np.concatenate(products).astype(np.float64)


def _hybrid(lexical: np.ndarray, similarity: np.ndarray) -> np.ndarray:
    """Average BM25 and similarity, each scaled to 0 to 1."""
    top = float(lexical.max()) if lexical.size else 0.0
    low = float(similarity.min()) if similarity.size else 0.0
    high = float(similarity.max()) if similarity.size else 0.0
    spread = (high - low) or 1.0
    return (
        HYBRID_WEIGHT * lexical / (top or 1.0)
        + (1 - HYBRID_WEIGHT) * (similarity - low) / spread
    )


def _read_matches(
    connection: sqlite3.Connection | None, matches: list[Match]
) -> list[reading.Passage]:
    """Return the passage of each match, in the matches' order.

    The passages of each file are read together.
    """
    numbers: dict[str, list[int]] = {}
    documents: dict[str, Document] = {}
    for match in matches:
        numbers.setdefault(match.document.file, []).append(match.passage)
        documents[match.document.file] = match.document
    found = {}
    for file, wanted in numbers.items():
        texts = index.read_passages(connection, documents[file].indexed,
                                    file, wanted)
        found.update(((file, number), text)
                     for number, text in zip(wanted, texts))
    return [found[(match.document.file, match.passage)] for match in matches]
