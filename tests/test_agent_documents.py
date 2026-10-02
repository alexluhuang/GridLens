"""The search_documents tool: cited passages of reference documents."""
from __future__ import annotations

from pathlib import Path

from gridlens.agent import document_tools
from gridlens.agent.library import worker
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import ToolService


ENDPOINT = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "embeddinggemma:latest"


def tools_for(folder: Path) -> ToolService:
    """Return the tools of a session whose projects hold folder."""
    context = SessionContext.create(None, (), "fixture:model", ENDPOINT,
                                    projects_dir=folder.parent)
    return ToolService(context)


def test_the_tool_lists_the_documents_and_says_which_it_cannot_read(
    reference_library
):
    listing = tools_for(reference_library).search_documents()
    assert listing["error"] is None
    rows = [(row["file"], row["pages"]) for row in listing["data"]["rows"]]
    assert rows == [("TPL-001-5.1.pdf", 2),
                    ("criteria/planning_criteria.md", 0), ("guide.html", 0)]
    assert any("scanned.pdf" in warning for warning in listing["warnings"])
    assert any("notes.docx" in warning for warning in listing["warnings"])


def test_the_tool_searches_and_cites_the_files_it_read(reference_library):
    tools = tools_for(reference_library)
    found = tools.search_documents("Rate B after a contingency", magnitude=2)
    data = found["data"]
    top = data["rows"][0]
    assert (top["file"], top["page"], top["page_label"], top["section"]) == (
        "TPL-001-5.1.pdf", 1, "5", "R1"
    )
    assert "Rate B applies" in top["text"] and "similarity" not in top
    assert data["retrieval"].startswith("BM25") and data["returned"] == 2
    assert data["total_matching"] >= 2
    cited = {Path(source["path"]).name
             for source in found["provenance"]["sources"]}
    assert cited <= {"TPL-001-5.1.pdf", "planning_criteria.md", "guide.html"}
    only = tools.search_documents("Rate B", document="criteria")
    assert {row["file"] for row in only["data"]["rows"]} == {
        "criteria/planning_criteria.md"
    }
    nothing = tools.search_documents("transfer capability")
    assert nothing["data"]["rows"] == []
    assert any("No passage contains" in warning
               for warning in nothing["warnings"])


def test_the_tool_says_where_to_put_documents(tmp_path):
    projects = tmp_path / "projects"
    context = SessionContext.create(None, (), "fixture:model", ENDPOINT,
                                    projects_dir=projects)
    tools = ToolService(context)
    missing = tools.search_documents("Rate B")
    assert missing["error"]["code"] == "NO_REFERENCE_DOCUMENTS"
    assert "Reference documents" in missing["error"]["remedy"]
    (projects / "Reference documents").mkdir(parents=True)
    empty = tools.search_documents("Rate B")
    assert empty["error"]["code"] == "NO_REFERENCE_DOCUMENTS"


def test_an_embedding_model_adds_similarity_and_embeds_passages_once(
    reference_library, local_embeddings
):
    tools = tools_for(reference_library)
    data = tools.search_documents("limits on voltage", magnitude=3)["data"]
    assert EMBEDDING_MODEL in data["retrieval"]
    assert "similarity" in data["rows"][0]
    assert data["rows"][0]["section"] in ("R2", "Voltage")
    assert data["total_matching"] == data["passages_searched"]
    # The query, which finds nothing indexed; then the indexer's probe
    # for the model's width and every passage; then the query again.
    assert len(local_embeddings) == data["passages_searched"] + 3
    assert local_embeddings[-1] == (
        "task: search result | query: limits on voltage"
    )
    local_embeddings.clear()
    tools.search_documents("voltage", magnitude=3)
    assert local_embeddings == ["task: search result | query: voltage"]


def test_files_still_being_indexed_are_named_and_left_out(
    reference_library, inline_indexer, monkeypatch
):
    tools = tools_for(reference_library)
    tools.search_documents("Rate B")
    monkeypatch.setattr(worker, "start", lambda folder, endpoint="":
                        inline_indexer.append(folder))
    (reference_library / "new.md").write_text("Rate B is the new limit.")
    found = tools.search_documents("Rate B")
    data = found["data"]
    assert data["being_indexed"] == ["new.md"]
    assert "new.md" not in {row["file"] for row in data["rows"]}
    assert any(warning.startswith("Not searched, because GridLens is still")
               and "new.md" in warning for warning in found["warnings"])
    assert inline_indexer[-1] == reference_library


def test_a_search_with_nothing_indexed_yet_says_indexing_is_underway(
    reference_library, monkeypatch
):
    monkeypatch.setattr(worker, "start", lambda folder, endpoint="": None)
    monkeypatch.setattr(document_tools, "FIRST_INDEX_WAIT_SECONDS", 0)
    refused = tools_for(reference_library).search_documents("Rate B")
    assert refused["error"]["code"] == "DOCUMENTS_INDEXING"
    assert "TPL-001-5.1.pdf" in refused["error"]["remedy"]
