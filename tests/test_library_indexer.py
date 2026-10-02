"""Bringing a folder's passage index up to date with its documents."""
from __future__ import annotations

import contextlib
import shutil

from gridlens.agent.library import cache, index, indexer, reading, vectors


ENDPOINT = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "embeddinggemma:latest"
READABLE = {"TPL-001-5.1.pdf", "criteria/planning_criteria.md", "guide.html"}


def indexed_files(folder):
    """Return the index's files by path and documents by SHA-256."""
    with contextlib.closing(index.open_for_reading(folder)) as connection:
        return index.read_files(connection), index.read_documents(connection)


def reads(monkeypatch):
    """Record the name of every file the indexer reads from disk."""
    names = []
    original = reading.extract

    def extract(path):
        names.append(path.name)
        return original(path)

    monkeypatch.setattr(reading, "extract", extract)
    return names


def test_update_indexes_readable_files_and_records_why_others_fail(
    reference_library
):
    indexer.update(reference_library)
    files, documents = indexed_files(reference_library)
    assert set(files) == READABLE | {"scanned.pdf"}
    scanned = documents[files["scanned.pdf"].sha256]
    assert scanned.error.startswith("it has no text GridLens can extract")
    standard = documents[files["TPL-001-5.1.pdf"].sha256]
    assert (standard.pages, standard.passages, standard.error) == (2, 2, "")
    assert standard.sha256 == cache.file_sha256(
        reference_library / "TPL-001-5.1.pdf"
    )


def test_a_file_is_read_once_until_it_changes(reference_library,
                                              monkeypatch):
    names = reads(monkeypatch)
    indexer.update(reference_library)
    assert sorted(names) == sorted(
        ["TPL-001-5.1.pdf", "planning_criteria.md", "guide.html",
         "scanned.pdf"]
    )
    names.clear()
    indexer.update(reference_library)
    assert names == []
    (reference_library / "guide.html").write_text("<p>Rate A applies.</p>")
    indexer.update(reference_library)
    assert names == ["guide.html"]


def test_an_index_built_again_reuses_the_cached_text(reference_library,
                                                     monkeypatch):
    indexer.update(reference_library)
    index.database_path(reference_library).unlink()
    names = reads(monkeypatch)
    indexer.update(reference_library)
    files, documents = indexed_files(reference_library)
    assert names == [] and set(files) == READABLE | {"scanned.pdf"}
    assert len(documents) == 4


def test_removed_files_are_forgotten_and_copies_are_read_once(
    reference_library, monkeypatch
):
    indexer.update(reference_library)
    (reference_library / "guide.html").unlink()
    (reference_library / "copies").mkdir()
    shutil.copy(reference_library / "TPL-001-5.1.pdf",
                reference_library / "copies/TPL.pdf")
    names = reads(monkeypatch)
    indexer.update(reference_library)
    files, documents = indexed_files(reference_library)
    assert names == []
    assert "guide.html" not in files and "copies/TPL.pdf" in files
    assert files["copies/TPL.pdf"].sha256 == (
        files["TPL-001-5.1.pdf"].sha256
    )
    assert {item.sha256 for item in files.values()} == set(documents)


def test_passages_are_embedded_once_with_the_installed_model(
    reference_library, local_embeddings
):
    indexer.update(reference_library, ENDPOINT)
    files, documents = indexed_files(reference_library)
    folder_index = reference_library / cache.INDEX_FOLDER
    passages = 0
    for item in files.values():
        document = documents[item.sha256]
        path = vectors.vector_file(folder_index, item.sha256,
                                   EMBEDDING_MODEL)
        if document.error:
            assert not path.exists()
        else:
            assert vectors.vectors_ready(path, document.passages, 6)
            passages += document.passages
    # One probe for the model's width, then every passage.
    assert len(local_embeddings) == 1 + passages
    assert local_embeddings[1].startswith(
        "title: TPL-001-5.1 Transmission System Planning Performance, R1"
        " | text: B. Requirements and Measures"
    )
    local_embeddings.clear()
    indexer.update(reference_library, ENDPOINT)
    assert len(local_embeddings) == 1


def test_vectors_of_another_width_are_embedded_again(reference_library,
                                                     local_embeddings):
    indexer.update(reference_library, ENDPOINT)
    first = len(local_embeddings)
    local_embeddings.width = 8
    indexer.update(reference_library, ENDPOINT)
    assert len(local_embeddings) == 2 * first
