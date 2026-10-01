"""The reference document search: passages of the user's documents, with their page and section."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import stat

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import gridlens.agent.documents as documents
from gridlens.agent.policy import AgentError
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import ToolService


def pdf(pages: list[list[str]], *, title: str = "", first_label: int = 0) -> bytes:
    """Return a PDF whose pages hold these lines of text, optionally titled and with printed page numbers."""
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    for lines in pages:
        page = writer.add_blank_page(612, 792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        text = "".join(f"({line}) Tj T* " for line in lines)
        stream.set_data(f"BT /F1 11 Tf 14 TL 72 720 Td {text}ET".encode("latin-1"))
        page.replace_contents(stream)
    if first_label:
        writer.set_page_label(0, len(pages) - 1, style="/D", start=first_label)
    if title:
        writer.add_metadata({"/Title": title})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


STANDARD = [
    ["B. Requirements and Measures", "R1. Each Planning Coordinator shall maintain System models.", "Rate B applies to the facility ratings after a contingency."],
    ["R2. Each Transmission Planner shall study P1 single contingency events.", "Steady state voltage limits apply to every bus."],
]


@pytest.fixture(autouse=True)
def no_ollama(monkeypatch):
    """Keep tests off any real Ollama: it does not answer unless a test fakes it."""
    def unavailable(endpoint, path, body=None, *, timeout=5):
        raise AgentError("OLLAMA_UNAVAILABLE", "Start Ollama.")
    monkeypatch.setattr(documents, "ollama_json", unavailable)


@pytest.fixture
def library(tmp_path) -> Path:
    """Return a Reference documents folder with a standard, a Markdown note, an HTML page, and files it cannot read."""
    folder = tmp_path / "projects" / "Reference documents"
    folder.mkdir(parents=True)
    (folder / "TPL-001-5.1.pdf").write_bytes(pdf(STANDARD, title="TPL-001-5.1 Transmission System Planning Performance", first_label=5))
    (folder / "criteria").mkdir()
    (folder / "criteria/planning_criteria.md").write_text("# Planning criteria\n\n## Ratings\n\nPost-contingency flows are compared with Rate B.\n")
    (folder / "guide.html").write_text("<html><head><title>Operating guide</title><script>var x = 'Rate B';</script></head><body><h2>Voltage</h2><p>Buses stay within 0.95 to 1.05 pu.</p></body></html>")
    (folder / "scanned.pdf").write_bytes(pdf([[]]))
    (folder / "notes.docx").write_bytes(b"PK")
    return folder


def tools_for(folder: Path) -> ToolService:
    return ToolService(SessionContext.create(None, (), "fixture:model", "http://127.0.0.1:11434", projects_dir=folder.parent))


def test_headings_are_found_by_pattern():
    assert [documents.heading(line) for line in (
        "R2.1.4. For each of the studies", "R1. Each Transmission Planner and Planning Coordinator shall maintain System models within its respective area for performing its studies.",
        "4.1. Functional Entities:", "B. Requirements and Measures", "Table 1 – Steady State Performance", "## Scope", "M3. Each Planning Coordinator",
        "The Planning Coordinator shall, within 30 days, do things.", "Page 3 of 24", "Rate B applies after a contingency.",
    )] == ["R2.1.4", "R1", "4.1. Functional Entities:", "B. Requirements and Measures", "Table 1 – Steady State Performance", "Scope", "M3", "", "", ""]
    assert documents.tokens("TPL-001-5.1 and the N-1 rule") == ["tpl-001-5.1", "tpl", "001", "5", "1", "n-1", "n", "1", "rule"]


def test_passages_keep_their_page_label_and_carry_the_section_across_pages(library):
    loaded = documents.load_library(library)
    standard = [passage for passage in loaded.passages if passage.file == "TPL-001-5.1.pdf"]
    assert [(passage.page, passage.page_label, passage.section) for passage in standard] == [(1, "5", "R1"), (2, "6", "R2")]
    assert standard[0].document == "TPL-001-5.1 Transmission System Planning Performance"
    html = next(passage for passage in loaded.passages if passage.file == "guide.html")
    assert (html.document, html.section, html.page) == ("Operating guide", "Voltage", None) and "var x" not in html.text
    markdown = next(passage for passage in loaded.passages if passage.file.endswith("planning_criteria.md"))
    assert (markdown.file, markdown.section) == ("criteria/planning_criteria.md", "Ratings")
    assert any(problem.startswith("scanned.pdf: it has no text GridLens can extract") for problem in loaded.problems)
    assert any(problem.startswith("notes.docx: GridLens reads PDF") for problem in loaded.problems)
    assert sorted(item["file"] for item in loaded.documents) == ["TPL-001-5.1.pdf", "criteria/planning_criteria.md", "guide.html"]


def test_extracted_text_is_cached_privately_until_the_file_changes(library, monkeypatch):
    documents.load_library(library)
    index = library / documents.INDEX_FOLDER
    assert stat.S_IMODE(index.stat().st_mode) == 0o700
    digest = hashlib.sha256((library / "TPL-001-5.1.pdf").read_bytes()).hexdigest()
    assert stat.S_IMODE((index / f"{digest}.json").stat().st_mode) == 0o600
    read = []
    original = documents.extract
    monkeypatch.setattr(documents, "extract", lambda path: read.append(path.name) or original(path))
    documents.load_library(library)
    assert read == []
    (library / "guide.html").write_text("<h1>Voltage</h1><p>Buses stay within 0.90 to 1.10 pu.</p>")
    loaded = documents.load_library(library)
    assert read == ["guide.html"] and any("0.90 to 1.10" in passage.text for passage in loaded.passages)


def test_the_tool_lists_and_searches_documents_and_cites_the_files_it_read(library):
    tools = tools_for(library)
    listing = tools.search_documents()
    assert listing["error"] is None
    assert [(row["file"], row["pages"]) for row in listing["data"]["rows"]] == [("TPL-001-5.1.pdf", 2), ("criteria/planning_criteria.md", 0), ("guide.html", 0)]
    assert any("scanned.pdf" in warning for warning in listing["warnings"])
    found = tools.search_documents("Rate B after a contingency", magnitude=2)
    data = found["data"]
    top = data["rows"][0]
    assert (top["file"], top["page"], top["page_label"], top["section"]) == ("TPL-001-5.1.pdf", 1, "5", "R1") and "Rate B applies" in top["text"]
    assert data["retrieval"].startswith("BM25") and data["returned"] == 2 and data["total_matching"] >= 2 and "similarity" not in top
    assert {Path(source["path"]).name for source in found["provenance"]["sources"]} <= {"TPL-001-5.1.pdf", "planning_criteria.md", "guide.html"}
    only = tools.search_documents("Rate B", document="criteria")["data"]["rows"]
    assert {row["file"] for row in only} == {"criteria/planning_criteria.md"}
    nothing = tools.search_documents("transfer capability")
    assert nothing["data"]["rows"] == [] and any("No passage contains" in warning for warning in nothing["warnings"])


def test_the_tool_says_where_to_put_documents(tmp_path):
    tools = ToolService(SessionContext.create(None, (), "fixture:model", "http://127.0.0.1:11434", projects_dir=tmp_path / "projects"))
    missing = tools.search_documents("Rate B")
    assert missing["error"]["code"] == "NO_REFERENCE_DOCUMENTS" and "Reference documents" in missing["error"]["remedy"]
    (tmp_path / "projects/Reference documents").mkdir(parents=True)
    assert tools.search_documents("Rate B")["error"]["code"] == "NO_REFERENCE_DOCUMENTS"


def test_an_installed_embedding_model_adds_similarity_and_its_vectors_are_cached(library, monkeypatch):
    """With an embedding model in the local Ollama, scores blend BM25 and similarity, and passages are embedded once."""
    embedded = []

    def vector(text: str) -> list[float]:
        words = documents.tokens(text)
        return [float(words.count(term)) for term in ("rate", "voltage", "contingency", "bus", "model")] + [0.1]

    def fake(endpoint, path, body=None, *, timeout=5):
        assert endpoint == "http://127.0.0.1:11434"
        if path == "/api/tags":
            return {"models": [{"name": "gemma4:31b"}, {"name": "embeddinggemma:latest"}]}
        if path == "/api/show":
            return {"capabilities": ["embedding"]}
        if path == "/api/embed":
            embedded.extend(body["input"])
            return {"embeddings": [vector(text) for text in body["input"]]}
        raise AssertionError(path)

    monkeypatch.setattr(documents, "ollama_json", fake)
    tools = tools_for(library)
    data = tools.search_documents("limits on voltage", magnitude=3)["data"]
    assert "embeddinggemma:latest" in data["retrieval"] and "similarity" in data["rows"][0]
    assert data["rows"][0]["section"] in ("R2", "Voltage") and data["total_matching"] == data["passages_searched"]
    first = len(embedded)
    assert first == data["passages_searched"] + 1
    # Passages go in EmbeddingGemma's document format, titled by document and section, and the query in its query format.
    assert "title: TPL-001-5.1 Transmission System Planning Performance, R1 | text: B. Requirements and Measures" in "\n".join(embedded)
    assert embedded[-1] == "task: search result | query: limits on voltage"
    tools.search_documents("voltage", magnitude=3)
    # Only the query is embedded the second time; the passages' vectors come from the cache.
    assert len(embedded) == first + 1 and list((library / documents.INDEX_FOLDER).glob("*.embeddinggemma_latest.*.f32"))
    assert "retrieval prompt format" in data["retrieval"]


def test_each_embedding_family_gets_its_model_cards_prompts():
    passage = documents.Passage("TPL-001-5.1", "tpl.pdf", 7, "7", "R2.1", "Each Planning Coordinator shall study P1 events.")
    assert documents.query_prompt("embeddinggemma:latest", "what  is TTC?") == "task: search result | query: what is TTC?"
    assert documents.document_prompt("embeddinggemma:300m", passage) == "title: TPL-001-5.1, R2.1 | text: Each Planning Coordinator shall study P1 events."
    assert documents.query_prompt("nomic-embed-text:v1.5", "TTC") == "search_query: TTC"
    assert documents.document_prompt("nomic-embed-text", passage).startswith("search_document: TPL-001-5.1, R2.1\n")
    assert documents.query_prompt("mxbai-embed-large", "TTC") == "Represent this sentence for searching relevant passages: TTC"
    assert documents.query_prompt("snowflake-arctic-embed2:568m", "TTC") == "query: TTC"
    assert documents.query_prompt("qwen3-embedding:0.6b", "TTC").startswith("Instruct: ") and documents.query_prompt("qwen3-embedding:0.6b", "TTC").endswith("\nQuery:TTC")
    # Models without retrieval prompts get the text itself, still titled.
    assert documents.query_prompt("bge-m3", "TTC") == "TTC"
    untitled = documents.Passage("notes", "notes.txt", None, "", "", "Rate B")
    assert documents.document_prompt("bge-m3", untitled) == "notes\nRate B"
    assert documents.document_prompt("embeddinggemma", documents.Passage("", "x.txt", None, "", "", "Rate B")) == "title: none | text: Rate B"


def test_changing_the_document_format_embeds_the_passages_again(library, monkeypatch):
    """Vectors are cached under the document format they were made with, so a new format does not reuse them."""
    calls = []

    def fake(endpoint, path, body=None, *, timeout=5):
        if path == "/api/tags":
            return {"models": [{"name": "embeddinggemma:latest"}]}
        if path == "/api/show":
            return {"capabilities": ["embedding"]}
        calls.append(len(body["input"]))
        return {"embeddings": [[1.0, float(len(text))] for text in body["input"]]}

    monkeypatch.setattr(documents, "ollama_json", fake)
    loaded = documents.load_library(library)
    documents.passage_embeddings(loaded, "http://127.0.0.1:11434", "embeddinggemma:latest")
    documents.passage_embeddings(loaded, "http://127.0.0.1:11434", "embeddinggemma:latest")
    once = sum(calls)
    monkeypatch.setitem(documents.EMBEDDING_PROMPTS, "embeddinggemma", ("q: {query}", "doc: {title}: {text}"))
    documents.passage_embeddings(loaded, "http://127.0.0.1:11434", "embeddinggemma:latest")
    assert once == len(loaded.passages) and sum(calls) == 2 * len(loaded.passages)
