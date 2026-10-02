"""Embedding vectors of passages, as float32 matrices from Ollama."""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gridlens.agent.library import cache, vectors
from gridlens.agent.library.reading import Passage
from gridlens.agent.policy import AgentError


ENDPOINT = "http://127.0.0.1:11434"
PASSAGE = Passage("TPL-001-5.1", "tpl.pdf", 7, "7", "R2.1",
                  "Each Planning Coordinator shall study P1 events.")


def fake_ollama(models, *, capabilities=None, remote=(), vector=None):
    """Return a stand-in for ollama_json and the inputs it embedded.

    models are the names /api/tags lists; capabilities maps a name to
    its /api/show capabilities; remote names models served elsewhere;
    vector turns one text into its embedding.
    """
    embedded = []

    def answer(endpoint, path, body=None, *, timeout=5):
        if path == "/api/tags":
            return {"models": [{"name": name} for name in models]}
        if path == "/api/show":
            name = body["model"]
            found = (capabilities or {}).get(name, ["embedding"])
            info = {"capabilities": found}
            if name in remote:
                info["remote_host"] = "https://ollama.invalid"
            return info
        embedded.append(list(body["input"]))
        return {"embeddings": [vector(text) for text in body["input"]]}

    return answer, embedded


def test_each_embedding_family_gets_its_model_cards_prompts():
    assert vectors.query_prompt("embeddinggemma:latest", "what  is TTC?") == (
        "task: search result | query: what is TTC?"
    )
    assert vectors.document_prompt("embeddinggemma:300m", PASSAGE) == (
        "title: TPL-001-5.1, R2.1 | text: Each Planning Coordinator shall "
        "study P1 events."
    )
    assert vectors.query_prompt("nomic-embed-text:v1.5", "TTC") == (
        "search_query: TTC"
    )
    assert vectors.document_prompt("nomic-embed-text", PASSAGE).startswith(
        "search_document: TPL-001-5.1, R2.1\n"
    )
    assert vectors.query_prompt("mxbai-embed-large", "TTC") == (
        "Represent this sentence for searching relevant passages: TTC"
    )
    assert vectors.query_prompt("snowflake-arctic-embed2:568m", "TTC") == (
        "query: TTC"
    )
    qwen = vectors.query_prompt("qwen3-embedding:0.6b", "TTC")
    assert qwen.startswith("Instruct: ") and qwen.endswith("\nQuery:TTC")


def test_a_model_without_retrieval_prompts_gets_the_titled_text():
    untitled = Passage("notes", "notes.txt", None, "", "", "Rate B")
    assert vectors.query_prompt("bge-m3", "TTC") == "TTC"
    assert vectors.document_prompt("bge-m3", untitled) == "notes\nRate B"
    nameless = Passage("", "x.txt", None, "", "", "Rate B")
    assert vectors.document_prompt("embeddinggemma", nameless) == (
        "title: none | text: Rate B"
    )


def test_the_preferred_local_embedding_model_is_chosen(monkeypatch):
    answer, __ = fake_ollama(
        ["gemma4:31b", "nomic-embed-text:latest", "embeddinggemma:cloud",
         "embeddinggemma:300m", "qwen3-embedding:0.6b"],
        capabilities={"qwen3-embedding:0.6b": ["completion"]},
        remote=("embeddinggemma:300m",),
    )
    monkeypatch.setattr(vectors, "ollama_json", answer)
    # The cloud tag and the remote model are passed over, and so is a
    # model that does not embed, which leaves nomic-embed-text.
    assert vectors.embedding_model(ENDPOINT) == "nomic-embed-text:latest"


def test_no_embedding_model_is_chosen_when_ollama_does_not_answer(
    monkeypatch
):
    def unavailable(endpoint, path, body=None, *, timeout=5):
        raise AgentError("OLLAMA_UNAVAILABLE", "Start Ollama.")

    monkeypatch.setattr(vectors, "ollama_json", unavailable)
    assert vectors.embedding_model(ENDPOINT) == ""


def test_texts_are_embedded_in_batches_as_unit_float32_rows(monkeypatch):
    answer, embedded = fake_ollama(
        [], vector=lambda text: [3.0, 4.0] if text != "zero" else [0.0, 0.0]
    )
    monkeypatch.setattr(vectors, "ollama_json", answer)
    texts = [f"passage {n}" for n in range(20)] + ["zero"]
    progress = []
    matrix = vectors.embed(ENDPOINT, "embeddinggemma:latest", texts,
                           progress.append)
    assert [len(batch) for batch in embedded] == [16, 5]
    assert progress == [16, 21]
    assert matrix.dtype == np.float32 and matrix.shape == (21, 2)
    assert np.allclose(matrix[0], [0.6, 0.8])
    assert matrix[-1].tolist() == [0.0, 0.0]


@pytest.mark.parametrize("vector", [
    lambda text: [],
    lambda text: [1.0] * len(text),
    lambda text: ["not a number"],
])
def test_a_response_without_equal_vectors_is_refused(monkeypatch, vector):
    answer, __ = fake_ollama([], vector=vector)
    monkeypatch.setattr(vectors, "ollama_json", answer)
    with pytest.raises(AgentError) as refused:
        vectors.embed(ENDPOINT, "embeddinggemma:latest", ["a", "bb"])
    assert refused.value.code == "EMBEDDING_FAILED"


def test_vector_files_are_named_for_the_model_and_document_format(
    monkeypatch, tmp_path
):
    document_format = b"title: {title} | text: {text}"
    format_hash = hashlib.sha256(document_format).hexdigest()[:8]
    path = vectors.vector_file(tmp_path, "abc", "embeddinggemma:latest")
    assert path.name == (
        f"abc.{cache.INDEX_VERSION}.embeddinggemma_latest.{format_hash}.f32"
    )
    monkeypatch.setitem(vectors.EMBEDDING_PROMPTS, "embeddinggemma",
                        ("q: {query}", "doc: {title}: {text}"))
    assert vectors.vector_file(tmp_path, "abc", "embeddinggemma") != path


def test_a_cached_matrix_loads_only_with_the_rows_and_width_expected(
    tmp_path
):
    path = tmp_path / "doc.f32"
    matrix = np.arange(12, dtype=np.float32).reshape(3, 4)
    vectors.save_vectors(path, matrix)
    assert np.array_equal(vectors.load_vectors(path, 3), matrix)
    assert np.array_equal(vectors.load_vectors(path, 3, 4), matrix)
    assert vectors.load_vectors(path, 3, 768) is None
    assert vectors.load_vectors(path, 5) is None
    assert vectors.load_vectors(tmp_path / "missing.f32", 3) is None
