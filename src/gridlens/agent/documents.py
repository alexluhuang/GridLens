"""Search the reference documents a user keeps beside their projects: standards, planning criteria, manuals.

The documents live in `<projects folder>/Reference documents/`. `gridlens.agent.library.reading` reads
their text and splits it into passages, and `gridlens.agent.library.cache` keeps that text in the
folder's `.gridlens-index/`, keyed by each file's SHA-256, so a file is read again only when it changes.

Passages are scored with BM25, which rewards exact terms such as "TPL-001" or "Rate B". When the local
Ollama has an embedding model, the score also counts how close each passage's meaning is to the query:
each score is scaled to 0 to 1 over the passages searched, and the two are averaged. Embeddings are
computed by Ollama on loopback and cached beside the text.

`gridlens.agent.library.vectors` writes the query and the passages in the embedding model's task prompts
and keeps each document's vectors as one float32 matrix, so a search is a matrix-vector product per
document.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

import numpy as np

from gridlens.agent.library import cache, vectors
from gridlens.agent.library.cache import INDEX_VERSION
from gridlens.agent.library.reading import Passage, document_files, extract, split_passages
from gridlens.agent.policy import AgentError, local_endpoint


BM25_K1 = 1.5
BM25_B = 0.75
HYBRID_WEIGHT = 0.5
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*")
_STOP_WORDS = frozenset("a an and are as at be by for from has have in is it its of on or that the this to was were which with".split())


@dataclass
class Library:
    """The passages of every readable document in a folder, and what could not be read."""

    folder: Path
    documents: list[dict]
    passages: list[Passage]
    problems: list[str]


def tokens(text: str) -> list[str]:
    """Split text into lower-case search terms, keeping identifiers such as tpl-001-5.1 whole and in parts."""
    found = []
    for match in _TOKEN.finditer(text.lower()):
        term = match.group()
        if term in _STOP_WORDS:
            continue
        found.append(term)
        parts = re.split(r"[.\-/]", term)
        if len(parts) > 1:
            found.extend(part for part in parts if part and part not in _STOP_WORDS)
    return found


def load_library(folder: Path) -> Library:
    """Read every document in folder, from the cache when a file has not changed since it was read."""
    index = cache.index_folder(folder)
    files, problems = document_files(folder)
    manifest_path = index / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    except ValueError:
        manifest = {}
    if manifest.get("version") != INDEX_VERSION:
        manifest = {"version": INDEX_VERSION, "files": {}}
    documents, passages, known = [], [], {}
    for path in files:
        relative = str(path.relative_to(folder))
        info = path.stat()
        entry = manifest["files"].get(relative) or {}
        if (entry.get("size"), entry.get("mtime_ns")) != (info.st_size, info.st_mtime_ns):
            entry = {"size": info.st_size, "mtime_ns": info.st_mtime_ns, "sha256": cache.file_sha256(path)}
        known[relative] = entry
        record = cache.load_text(index, entry["sha256"])
        if record is None:
            try:
                title, pages = extract(path)
            except ValueError as exc:
                problems.append(f"{relative}: {exc}.")
                record = {"error": str(exc)}
            else:
                record = {"title": title, "pages": pages}
            cache.save_text(index, entry["sha256"], record)
        if "error" in record:
            if f"{relative}: {record['error']}." not in problems:
                problems.append(f"{relative}: {record['error']}.")
            continue
        pages = [(page, label, text) for page, label, text in record["pages"]]
        found = split_passages(record["title"], relative, pages)
        documents.append({"document": record["title"], "file": relative, "path": str(path), "pages": sum(1 for page, _, _ in pages if page is not None), "passages": len(found), "sha256": entry["sha256"]})
        passages.extend(found)
    if known != manifest["files"]:
        cache.private_write(manifest_path, json.dumps({"version": INDEX_VERSION, "files": known}, indent=2).encode("utf-8"))
    return Library(folder, documents, passages, problems)


def bm25_scores(passages: list[Passage], query: str) -> list[float]:
    """Return the BM25 score of every passage for query."""
    wanted = list(dict.fromkeys(tokens(query)))
    if not wanted or not passages:
        return [0.0] * len(passages)
    counts = [Counter(tokens(f"{passage.section}\n{passage.text}")) for passage in passages]
    lengths = [sum(count.values()) for count in counts]
    average = sum(lengths) / len(lengths) or 1.0
    total = len(passages)
    frequency = {term: sum(1 for count in counts if term in count) for term in wanted}
    scores = []
    for count, length in zip(counts, lengths):
        score = 0.0
        for term in wanted:
            seen = count.get(term, 0)
            if not seen:
                continue
            inverse = math.log(1 + (total - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += inverse * seen * (BM25_K1 + 1) / (seen + BM25_K1 * (1 - BM25_B + BM25_B * length / average))
        scores.append(score)
    return scores


def passage_embeddings(library: Library, endpoint: str, model: str, dimensions: int = 0) -> list[np.ndarray]:
    """Return the vectors of each document's passages as a float32 matrix, in the library's order.

    Only documents with no cached matrix, or one of another width when dimensions is given, are embedded.
    Documents without passages have no matrix.
    """
    index = cache.index_folder(library.folder)
    by_file: dict[str, list[Passage]] = {}
    for passage in library.passages:
        by_file.setdefault(passage.file, []).append(passage)
    matrices = []
    for document in library.documents:
        passages = by_file.get(document["file"], [])
        if not passages:
            continue
        path = vectors.vector_file(index, document["sha256"], model)
        matrix = vectors.load_vectors(path, len(passages), dimensions)
        if matrix is None:
            matrix = vectors.embed(endpoint, model, [vectors.document_prompt(model, passage) for passage in passages])
            vectors.save_vectors(path, matrix)
        matrices.append(matrix)
    return matrices


def search(library: Library, query: str, endpoint: str = "", document: str = "") -> tuple[list[tuple[Passage, float, float, float | None]], str]:
    """Rank the passages of a library for query, best first.

    Returns (passage, score, bm25, similarity) for every passage whose BM25 score is above 0, or for every
    passage when embeddings are used, and a description of the scoring. document limits the search to
    files whose name or title contains it.
    """
    wanted = document.strip().casefold()
    passages = [passage for passage in library.passages if not wanted or wanted in passage.file.casefold() or wanted in passage.document.casefold()]
    lexical = bm25_scores(passages, query)
    model = ""
    if endpoint and passages:
        try:
            model = vectors.embedding_model(local_endpoint(endpoint))
        except AgentError:
            model = ""
    if not model:
        ranked = sorted((item for item in zip(passages, lexical) if item[1] > 0), key=lambda item: -item[1])
        return [(passage, score, score, None) for passage, score in ranked], "BM25 (no local embedding model is installed in Ollama)"
    origin = local_endpoint(endpoint)
    matrices = passage_embeddings(library, origin, model)
    query_vector = vectors.query_vector(origin, model, query)
    if any(matrix.shape[1] != query_vector.size for matrix in matrices):
        # A cached matrix of another width came from another version of the model.
        matrices = passage_embeddings(library, origin, model, query_vector.size)
    # One matrix-vector product per document, so a document's similarities do not depend on the others.
    closeness = np.concatenate([matrix @ query_vector for matrix in matrices]) if matrices else np.zeros(0, np.float32)
    position = {id(passage): number for number, passage in enumerate(library.passages)}
    similarity = closeness[[position[id(passage)] for passage in passages]].tolist()
    top_lexical = max(lexical, default=0.0) or 1.0
    low, high = min(similarity, default=0.0), max(similarity, default=0.0)
    spread = (high - low) or 1.0
    scored = [
        (passage, HYBRID_WEIGHT * lexical_score / top_lexical + (1 - HYBRID_WEIGHT) * (close - low) / spread, lexical_score, close)
        for passage, lexical_score, close in zip(passages, lexical, similarity)
    ]
    scored.sort(key=lambda item: -item[1])
    prompted = "in the model's retrieval prompt format" if vectors.embedding_prompts(model) != vectors.PLAIN_PROMPTS else "as plain text"
    return scored, f"BM25 and {model} embeddings (query and passages {prompted}), each scaled to 0 to 1 over the passages searched, averaged"
