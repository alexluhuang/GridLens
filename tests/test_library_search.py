"""Searching the reference library's indexed documents."""
from __future__ import annotations

from gridlens.agent.library import indexer, search


ENDPOINT = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "embeddinggemma:latest"


def test_a_search_ranks_the_passages_that_hold_the_query(reference_library):
    indexer.update(reference_library)
    result = search.find(reference_library, "Rate B after a contingency",
                         limit=2)
    top = result.passages[0]
    assert (top.file, top.page, top.page_label, top.section) == (
        "TPL-001-5.1.pdf", 1, "5", "R1"
    )
    assert "Rate B applies" in top.text
    assert result.retrieval == search.BM25_ONLY
    assert len(result.matches) == 2 and result.total >= 2
    assert [match.score for match in result.matches] == sorted(
        (match.score for match in result.matches), reverse=True
    )
    assert all(match.similarity is None for match in result.matches)


def test_a_search_finds_nothing_without_a_query_term(reference_library):
    indexer.update(reference_library)
    result = search.find(reference_library, "transfer capability")
    assert (result.matches, result.passages, result.total) == ([], [], 0)


def test_the_document_filter_matches_file_names_and_titles(
    reference_library
):
    indexer.update(reference_library)
    by_folder = search.find(reference_library, "Rate B",
                            document="criteria")
    assert {item.file for item in by_folder.passages} == {
        "criteria/planning_criteria.md"
    }
    by_title = search.find(reference_library, "voltage",
                           document="operating guide")
    assert [item.file for item in by_title.searched] == ["guide.html"]


def test_a_blank_query_lists_the_documents_and_their_problems(
    reference_library
):
    indexer.update(reference_library)
    result = search.find(reference_library, "")
    assert [item.file for item in result.searched] == [
        "TPL-001-5.1.pdf", "criteria/planning_criteria.md", "guide.html",
    ]
    assert result.matches == [] and result.catalog.pending == []
    assert result.catalog.problems[0].startswith("notes.docx: GridLens")
    assert result.catalog.problems[1].startswith(
        "scanned.pdf: it has no text GridLens can extract"
    )


def test_files_the_index_does_not_hold_yet_are_pending(reference_library):
    assert search.find(reference_library, "Rate B").catalog.pending == [
        "TPL-001-5.1.pdf", "criteria/planning_criteria.md", "guide.html",
        "scanned.pdf",
    ]
    indexer.update(reference_library)
    (reference_library / "new.md").write_text("Rate B is the limit.")
    (reference_library / "guide.html").write_text("<p>Rate B.</p>")
    result = search.find(reference_library, "Rate B")
    assert result.catalog.pending == ["guide.html", "new.md"]
    assert {item.file for item in result.passages} == {
        "TPL-001-5.1.pdf", "criteria/planning_criteria.md",
    }


def test_with_an_embedding_model_documents_wait_for_their_vectors(
    reference_library, local_embeddings
):
    indexer.update(reference_library)
    waiting = search.find(reference_library, "voltage", ENDPOINT)
    assert waiting.searched == [] and len(waiting.catalog.pending) == 3
    indexer.update(reference_library, ENDPOINT)
    result = search.find(reference_library, "limits on voltage", ENDPOINT,
                         limit=3)
    assert result.catalog.pending == [] and result.catalog.model == (
        EMBEDDING_MODEL
    )
    assert EMBEDDING_MODEL in result.retrieval
    assert "retrieval prompt format" in result.retrieval
    assert result.passages[0].section in ("R2", "Voltage")
    passages = sum(item.indexed.passages for item in result.searched)
    assert result.total == passages
    assert local_embeddings[-1] == (
        "task: search result | query: limits on voltage"
    )
    assert all(0.0 <= match.score <= 1.0 for match in result.matches)
    assert all(match.similarity is not None for match in result.matches)
