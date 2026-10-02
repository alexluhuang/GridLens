"""Search the reference documents a user keeps beside their projects: standards, planning criteria, manuals.

The documents live in `<projects folder>/Reference documents/`. `gridlens.agent.library.reading` reads
their text and splits it into passages, and `gridlens.agent.library.cache` keeps that text in the
folder's `.gridlens-index/`, keyed by each file's SHA-256, so a file is read again only when it changes.

Passages are scored with BM25, which rewards exact terms such as "TPL-001" or "Rate B". When the local
Ollama has an embedding model, the score also counts how close each passage's meaning is to the query:
each score is scaled to 0 to 1 over the passages searched, and the two are averaged. Embeddings are
computed by Ollama on loopback and cached beside the text.

Retrieval embedding models are trained with task prompts: a query is written one way and a document
another, such as "task: search result | query: ..." and "title: ... | text: ..." for EmbeddingGemma.
Ollama adds no prompt of its own, so `EMBEDDING_PROMPTS` gives each supported family's formats, from its
model card, and `embedding_prompts` picks the installed model's. A change to a document format changes the
cache file name, so passages embedded the old way are embedded again.
"""
from __future__ import annotations

from array import array
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from gridlens.agent.library import cache
from gridlens.agent.library.cache import INDEX_VERSION
from gridlens.agent.library.reading import Passage, document_files, extract, split_passages
from gridlens.agent.policy import AgentError, local_endpoint, ollama_json


BM25_K1 = 1.5
BM25_B = 0.75
HYBRID_WEIGHT = 0.5
# Embedding models from the Ollama library, in the order GridLens prefers them when several are installed.
EMBEDDING_FAMILIES = ("embeddinggemma", "qwen3-embedding", "nomic-embed-text", "mxbai-embed-large", "bge-m3", "snowflake-arctic-embed2", "snowflake-arctic-embed", "granite-embedding", "all-minilm")
EMBED_BATCH = 16
# Each family's retrieval prompts, as (query format, document format), from its model card. {query} is the
# search; {title} is the passage's document and section; {text} is the passage. EmbeddingGemma: "task:
# search result | query:" and "title: | text:"; nomic-embed-text: "search_query:" and "search_document:";
# mxbai-embed-large and snowflake-arctic-embed (v1): a query instruction only; snowflake-arctic-embed2:
# "query: "; qwen3-embedding: "Instruct: <task>\nQuery:<query>", documents as they are. bge-m3,
# granite-embedding, and all-minilm take text without prompts.
EMBEDDING_PROMPTS = {
    "embeddinggemma": ("task: search result | query: {query}", "title: {title} | text: {text}"),
    "nomic-embed-text": ("search_query: {query}", "search_document: {title}\n{text}"),
    "mxbai-embed-large": ("Represent this sentence for searching relevant passages: {query}", "{title}\n{text}"),
    "snowflake-arctic-embed": ("Represent this sentence for searching relevant passages: {query}", "{title}\n{text}"),
    "snowflake-arctic-embed2": ("query: {query}", "{title}\n{text}"),
    "qwen3-embedding": (
        "Instruct: Given a question about transmission planning, retrieve passages from standards, planning criteria, and manuals that answer it\nQuery:{query}",
        "{title}\n{text}",
    ),
}
PLAIN_PROMPTS = ("{query}", "{title}\n{text}")
EMBED_TIMEOUT_SECONDS = 120
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


def embedding_model(endpoint: str) -> str:
    """Return the name of an installed local embedding model, or "" when Ollama has none or does not answer."""
    try:
        names = [str(item.get("name", "")) for item in ollama_json(endpoint, "/api/tags").get("models", [])]
    except AgentError:
        return ""
    for family in EMBEDDING_FAMILIES:
        for name in sorted(names):
            if name.split(":")[0].split("/")[-1] != family or "cloud" in name.split(":")[-1].lower():
                continue
            try:
                info = ollama_json(endpoint, "/api/show", {"model": name})
            except AgentError:
                continue
            if "embedding" in info.get("capabilities", ["embedding"]) and not (info.get("remote_host") or info.get("remote_model")):
                return name
    return ""


def _embed(endpoint: str, model: str, texts: list[str]) -> list[list[float]]:
    """Return an embedding for each text from the local Ollama, in batches."""
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        result = ollama_json(endpoint, "/api/embed", {"model": model, "input": batch}, timeout=EMBED_TIMEOUT_SECONDS)
        found = result.get("embeddings")
        if not isinstance(found, list) or len(found) != len(batch):
            raise AgentError("EMBEDDING_FAILED", f"Ollama returned no embeddings from {model}.")
        vectors.extend(found)
    return vectors


def embedding_prompts(model: str) -> tuple[str, str]:
    """Return the (query, document) prompt formats of an embedding model's family, or plain text for one without prompts."""
    family = model.split(":")[0].split("/")[-1]
    return EMBEDDING_PROMPTS.get(family, PLAIN_PROMPTS)


def query_prompt(model: str, query: str) -> str:
    """Return a search query written as the embedding model expects a retrieval query."""
    return embedding_prompts(model)[0].format(query=" ".join(query.split()))


def document_prompt(model: str, passage: Passage) -> str:
    """Return a passage written as the embedding model expects a retrieval document, titled by its document and section."""
    title = ", ".join(part for part in (passage.document, passage.section) if part) or "none"
    return embedding_prompts(model)[1].format(title=title, text=passage.text)


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def passage_embeddings(library: Library, endpoint: str, model: str) -> list[list[float]]:
    """Return a unit embedding of every passage, computing only those of documents not embedded before."""
    index = cache.index_folder(library.folder)
    # The document format is part of the name, so vectors made with another format are not reused.
    prompt = hashlib.sha256(embedding_prompts(model)[1].encode()).hexdigest()[:8]
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", model) + f".{prompt}"
    vectors: list[list[float]] = []
    by_file: dict[str, list[Passage]] = {}
    for passage in library.passages:
        by_file.setdefault(passage.file, []).append(passage)
    for document in library.documents:
        passages = by_file.get(document["file"], [])
        path = index / f"{document['sha256']}.{INDEX_VERSION}.{slug}.f32"
        stored = array("f")
        if path.is_file():
            stored.frombytes(path.read_bytes())
        if passages and len(stored) and len(stored) % len(passages) == 0:
            size = len(stored) // len(passages)
            vectors.extend(list(stored[offset:offset + size]) for offset in range(0, len(stored), size))
            continue
        found = [_unit(vector) for vector in _embed(endpoint, model, [document_prompt(model, passage) for passage in passages])]
        cache.private_write(path, array("f", [value for vector in found for value in vector]).tobytes())
        vectors.extend(found)
    return vectors


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
            model = embedding_model(local_endpoint(endpoint))
        except AgentError:
            model = ""
    if not model:
        ranked = sorted((item for item in zip(passages, lexical) if item[1] > 0), key=lambda item: -item[1])
        return [(passage, score, score, None) for passage, score in ranked], "BM25 (no local embedding model is installed in Ollama)"
    everything = passage_embeddings(library, local_endpoint(endpoint), model)
    lookup = {id(passage): vector for passage, vector in zip(library.passages, everything)}
    (query_vector,) = [_unit(vector) for vector in _embed(local_endpoint(endpoint), model, [query_prompt(model, query)])]
    similarity = [sum(a * b for a, b in zip(query_vector, lookup[id(passage)])) for passage in passages]
    top_lexical = max(lexical, default=0.0) or 1.0
    low, high = min(similarity, default=0.0), max(similarity, default=0.0)
    spread = (high - low) or 1.0
    scored = [
        (passage, HYBRID_WEIGHT * lexical_score / top_lexical + (1 - HYBRID_WEIGHT) * (close - low) / spread, lexical_score, close)
        for passage, lexical_score, close in zip(passages, lexical, similarity)
    ]
    scored.sort(key=lambda item: -item[1])
    prompted = "in the model's retrieval prompt format" if embedding_prompts(model) != PLAIN_PROMPTS else "as plain text"
    return scored, f"BM25 and {model} embeddings (query and passages {prompted}), each scaled to 0 to 1 over the passages searched, averaged"
