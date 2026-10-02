"""Embedding vectors of passages, from a local Ollama embedding model.

When the local Ollama has an embedding model, each passage is turned
into a vector that captures its meaning, and a search counts how close
each passage's vector is to the query's. The vectors are computed by
Ollama on loopback and sent nowhere else.

Retrieval embedding models are trained with task prompts: a query is
written one way and a document another, such as "task: search result
| query: ..." and "title: ... | text: ..." for EmbeddingGemma. Ollama
adds no prompt of its own, so `EMBEDDING_PROMPTS` gives each supported
family's formats, from its model card, and `embedding_prompts` picks
the installed model's.

A document's vectors are one float32 matrix, a row per passage, each
row scaled to length 1. The matrix is cached in the folder's
`.gridlens-index/` as raw float32 values, row after row, so loading it
is one read and comparing a query with every passage of the document
is one matrix-vector product. Every passage is compared, so the same
documents always rank the same way. The cache file is named for the
document's SHA-256, the text version, the model, and the document
format, so a change to any of them embeds the passages again.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

import numpy as np

from gridlens.agent.library import cache
from gridlens.agent.library.reading import Passage
from gridlens.agent.policy import AgentError, ollama_json


# Embedding models from the Ollama library, in the order GridLens
# prefers them when several are installed.
EMBEDDING_FAMILIES = (
    "embeddinggemma", "qwen3-embedding", "nomic-embed-text",
    "mxbai-embed-large", "bge-m3", "snowflake-arctic-embed2",
    "snowflake-arctic-embed", "granite-embedding", "all-minilm",
)
EMBED_BATCH = 16
EMBED_TIMEOUT_SECONDS = 120
_RETRIEVAL_INSTRUCTION = (
    "Represent this sentence for searching relevant passages: {query}"
)
_QWEN3_INSTRUCTION = (
    "Instruct: Given a question about transmission planning, retrieve "
    "passages from standards, planning criteria, and manuals that answer "
    "it\nQuery:{query}"
)
# Each family's retrieval prompts, as (query format, document format),
# from its model card. {query} is the search; {title} is the passage's
# document and section; {text} is the passage. bge-m3,
# granite-embedding, and all-minilm take text without prompts.
EMBEDDING_PROMPTS = {
    "embeddinggemma": (
        "task: search result | query: {query}",
        "title: {title} | text: {text}",
    ),
    "nomic-embed-text": (
        "search_query: {query}", "search_document: {title}\n{text}",
    ),
    "mxbai-embed-large": (_RETRIEVAL_INSTRUCTION, "{title}\n{text}"),
    "snowflake-arctic-embed": (_RETRIEVAL_INSTRUCTION, "{title}\n{text}"),
    "snowflake-arctic-embed2": ("query: {query}", "{title}\n{text}"),
    "qwen3-embedding": (_QWEN3_INSTRUCTION, "{title}\n{text}"),
}
PLAIN_PROMPTS = ("{query}", "{title}\n{text}")
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_FLOAT_BYTES = np.dtype(np.float32).itemsize


def model_family(model: str) -> str:
    """Return a model's family: its Ollama name without tag or owner."""
    return model.split(":")[0].split("/")[-1]


def embedding_model(endpoint: str) -> str:
    """Return the name of an installed local embedding model.

    Returns "" when Ollama has none or does not answer. A cloud model,
    or one Ollama serves from another host, is never chosen.
    """
    try:
        listed = ollama_json(endpoint, "/api/tags").get("models", [])
    except AgentError:
        listed = []
    names = sorted(str(item.get("name", "")) for item in listed)
    candidates = (
        name for family in EMBEDDING_FAMILIES for name in names
        if model_family(name) == family
    )
    return next(
        (name for name in candidates if _is_local_embedder(endpoint, name)),
        "",
    )


def _is_local_embedder(endpoint: str, name: str) -> bool:
    """Say whether a model embeds text and runs on this machine."""
    if "cloud" in name.split(":")[-1].lower():
        return False
    try:
        info = ollama_json(endpoint, "/api/show", {"model": name})
    except AgentError:
        return False
    embeds = "embedding" in info.get("capabilities", ["embedding"])
    remote = info.get("remote_host") or info.get("remote_model")
    return embeds and not remote


def embedding_prompts(model: str) -> tuple[str, str]:
    """Return a model family's (query, document) prompt formats.

    A family without retrieval prompts gets the text itself.
    """
    return EMBEDDING_PROMPTS.get(model_family(model), PLAIN_PROMPTS)


def query_prompt(model: str, query: str) -> str:
    """Write a search query as the embedding model expects a query."""
    query_format = embedding_prompts(model)[0]
    return query_format.format(query=" ".join(query.split()))


def document_prompt(model: str, passage: Passage) -> str:
    """Write a passage as the embedding model expects a document.

    The passage is titled by its document and section.
    """
    parts = (passage.document, passage.section)
    title = ", ".join(part for part in parts if part) or "none"
    document_format = embedding_prompts(model)[1]
    return document_format.format(title=title, text=passage.text)


def embed(endpoint: str, model: str, texts: list[str]) -> np.ndarray:
    """Return the unit embedding of each text, as float32 matrix rows.

    Texts go to the local Ollama in batches of EMBED_BATCH. Raises
    AgentError when Ollama does not return one vector per text, all of
    the same length.
    """
    batches = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        result = ollama_json(
            endpoint, "/api/embed", {"model": model, "input": batch},
            timeout=EMBED_TIMEOUT_SECONDS,
        )
        batches.append(_embedding_rows(result, model, len(batch)))
    if batches:
        matrix = _unit_rows(np.concatenate(batches))
    else:
        matrix = np.zeros((0, 0), dtype=np.float32)
    return matrix


def _embedding_rows(result: dict, model: str, count: int) -> np.ndarray:
    """Return the vectors in an /api/embed response as matrix rows."""
    found = result.get("embeddings")
    failed = AgentError(
        "EMBEDDING_FAILED", f"Ollama returned no embeddings from {model}."
    )
    if not isinstance(found, list) or len(found) != count:
        raise failed
    try:
        rows = np.asarray(found, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise failed from exc
    if rows.ndim != 2 or not rows.shape[1]:
        raise failed
    return rows


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    """Scale every row to length 1, leaving a zero row as it is."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def query_vector(endpoint: str, model: str, query: str) -> np.ndarray:
    """Return the unit embedding of a search query, in its prompt."""
    return embed(endpoint, model, [query_prompt(model, query)])[0]


def model_dimensions(endpoint: str, model: str) -> int:
    """Return how many values the model's vectors have now.

    A model pulled again can change its width, so the indexer asks the
    model itself before it trusts a cached matrix.
    """
    return int(query_vector(endpoint, model, "dimensions").size)


def vector_file(index: Path, sha256: str, model: str) -> Path:
    """Return where a document's vectors from a model are cached.

    The name holds the document format's hash, so passages embedded in
    another format are not reused.
    """
    document_format = embedding_prompts(model)[1].encode("utf-8")
    format_hash = hashlib.sha256(document_format).hexdigest()[:8]
    slug = _UNSAFE_NAME_CHARS.sub("_", model)
    name = f"{sha256}.{cache.INDEX_VERSION}.{slug}.{format_hash}.f32"
    return index / name


def load_vectors(
    path: Path, count: int, dimensions: int = 0
) -> np.ndarray | None:
    """Return a cached matrix of count rows, or None if it is unusable.

    A missing file, or one whose size is not count rows (of dimensions
    columns, when dimensions is not 0), is unusable.
    """
    matrix = None
    if count and path.is_file():
        values = np.fromfile(path, dtype=np.float32)
        width = values.size // count
        whole = width > 0 and values.size == width * count
        if whole and dimensions in (0, width):
            matrix = values.reshape(count, width)
    return matrix


def vectors_ready(path: Path, count: int, dimensions: int = 0) -> bool:
    """Say whether a matrix of count rows is cached, by its size alone.

    With dimensions, its rows must also be that wide.
    """
    size = path.stat().st_size if path.is_file() else 0
    values, remainder = divmod(size, _FLOAT_BYTES)
    whole = count > 0 and values > 0 and not remainder
    return whole and values % count == 0 and dimensions in (
        0, values // count
    )


def save_vectors(path: Path, matrix: np.ndarray) -> None:
    """Cache a document's vectors privately, in one step."""
    data = np.ascontiguousarray(matrix, dtype=np.float32).tobytes()
    cache.private_write(path, data)
