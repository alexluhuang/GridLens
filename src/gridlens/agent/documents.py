"""Search the reference documents a user keeps beside their projects: standards, planning criteria, manuals.

The documents live in `<projects folder>/Reference documents/`, a folder the user fills. GridLens reads the
PDF, plain text, Markdown, and HTML files in it, and sends them nowhere. Each file is split into passages
that keep their document, page, and section, so an answer can cite "TPL-001-5.1, page 7, R2.1".

Reading a PDF is slow, so the text of each file is cached in the folder's `.gridlens-index/`, keyed by the
file's SHA-256, and read again only when the file changes. The cache holds the documents' text, so it is
written with the same private permissions as a session.

Passages are scored with BM25, which rewards exact terms such as "TPL-001" or "Rate B". When the local
Ollama has an embedding model, the score also counts how close each passage's meaning is to the query:
each score is scaled to 0 to 1 over the passages searched, and the two are averaged. Embeddings are
computed by Ollama on loopback and cached beside the text.

A page number is the PDF's own page, and a page label is the number printed on the page when the PDF
records one. A section is the nearest heading above the passage, found by pattern (numbered headings,
NERC requirement and measure IDs such as R2.1, lettered parts such as "B. Requirements and Measures",
tables and attachments, and Markdown headings), so it is a best guess that a reader should check.
"""
from __future__ import annotations

from array import array
from collections import Counter
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import logging
import math
import os
from pathlib import Path
import re

from gridlens.agent.policy import AgentError, local_endpoint, ollama_json


INDEX_FOLDER = ".gridlens-index"
# Changing how text is extracted or split changes this, so every cached file is read again.
INDEX_VERSION = "2026.09.30"
SUFFIXES = {".pdf": "pdf", ".txt": "text", ".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html"}
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_DOCUMENTS = 1000
PASSAGE_CHARS = 1200
# A heading this close to the start of a passage starts a new passage instead of joining the last one.
MIN_PASSAGE_CHARS = 200
BM25_K1 = 1.5
BM25_B = 0.75
HYBRID_WEIGHT = 0.5
# Embedding models from the Ollama library, in the order GridLens prefers them when several are installed.
EMBEDDING_FAMILIES = ("embeddinggemma", "qwen3-embedding", "nomic-embed-text", "mxbai-embed-large", "bge-m3", "snowflake-arctic-embed", "granite-embedding", "all-minilm")
EMBED_BATCH = 16
EMBED_TIMEOUT_SECONDS = 120
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*")
_STOP_WORDS = frozenset("a an and are as at be by for from has have in is it its of on or that the this to was were which with".split())
# A requirement or measure, such as "R2.1. Each Planning Coordinator shall ...", begins a section however long its line.
_REQUIREMENT = re.compile(r"^(?P<text>[RM]\d+(?:\.\d+)*)\.?(?:\s+[A-Z(].*)?$")
_HEADINGS = (
    re.compile(r"^#{1,6}\s+(?P<text>.{1,100})$"),
    re.compile(r"^(?P<text>[A-H]\.\s+[A-Z][A-Za-z,&/ -]{2,70})$"),
    re.compile(r"^(?P<text>(?:Attachment|Appendix|Table|Section|Part|Chapter|Exhibit)\s+[0-9A-Z]+(?:\.\d+)*\b[^.;]{0,80})$"),
    re.compile(r"^(?P<text>\d+(?:\.\d+){0,4}\.?\s+[A-Z][^.;,]{1,80})$"),
)


@dataclass(frozen=True)
class Passage:
    """One passage of a document, with where it is: the page, its printed label, and the section."""

    document: str
    file: str
    page: int | None
    page_label: str
    section: str
    text: str


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


def heading(line: str) -> str:
    """Return the section a line begins, or "" when it is ordinary text."""
    text = " ".join(line.split())
    requirement = _REQUIREMENT.match(text)
    if requirement:
        return requirement.group("text")
    if not text or len(text) > 120:
        return ""
    for pattern in _HEADINGS:
        match = pattern.match(text)
        if match:
            return match.group("text").strip()
    return ""


def split_passages(document: str, file: str, pages: list[tuple[int | None, str, str]]) -> list[Passage]:
    """Split a document's pages into passages that start at headings and hold about PASSAGE_CHARS.

    pages holds (page number, page label, text). A section carries over from page to page until the next
    heading.
    """
    passages = []
    section = ""
    for number, label, text in pages:
        lines: list[str] = []
        size = 0
        start_section = section
        # While a passage holds only headings, it takes the latest, most specific one as its section.
        headings_only = True

        def flush() -> None:
            body = "\n".join(lines).strip()
            if body:
                passages.append(Passage(document, file, number, label, start_section, body))

        for raw in text.splitlines():
            line = raw.rstrip()
            found = heading(line)
            if found and size >= MIN_PASSAGE_CHARS:
                flush()
                lines, size, headings_only = [], 0, True
            if found:
                section = found
                if headings_only:
                    start_section = section
            if size + len(line) > PASSAGE_CHARS and lines:
                flush()
                lines, size, start_section, headings_only = [], 0, section, True
            lines.append(line)
            size += len(line) + 1
            if line.strip() and not found:
                headings_only = False
        flush()
    return passages


class _HTMLText(HTMLParser):
    """Collect the text of an HTML page, one line per block, without scripts or styles."""

    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skipping += 1
        if tag == "title":
            self.in_title = True
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skipping:
            self.skipping -= 1
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skipping:
            self.parts.append(data)


def extract(path: Path) -> tuple[str, list[tuple[int | None, str, str]]]:
    """Return a file's title and its pages as (page number, page label, text).

    A text, Markdown, or HTML file is one page with no number. Raises ValueError, with a sentence for the
    user, when the file cannot be read.
    """
    kind = SUFFIXES[path.suffix.lower()]
    if kind == "pdf":
        return _extract_pdf(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    if kind == "html":
        parser = _HTMLText()
        parser.feed(text)
        body = re.sub(r"\n\s*\n+", "\n\n", "".join(parser.parts))
        return (" ".join(parser.title.split()) or path.stem), [(None, "", body)]
    return path.stem, [(None, "", text)]


def _extract_pdf(path: Path) -> tuple[str, list[tuple[int | None, str, str]]]:
    """Return a PDF's title and the text and printed label of each page."""
    import pypdf
    from pypdf.errors import PyPdfError

    # pypdf logs what it skips in a malformed page; the passages it returns are what matters here.
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("it is encrypted with a password")
        labels = list(reader.page_labels)
        pages = []
        for index, page in enumerate(reader.pages):
            pages.append((index + 1, labels[index] if index < len(labels) else str(index + 1), page.extract_text() or ""))
        title = str((reader.metadata or {}).get("/Title") or "").strip()
    except (PyPdfError, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError, NotImplementedError, RecursionError) as exc:
        raise ValueError(f"it could not be read as a PDF ({exc})") from exc
    if not any(text.strip() for _, _, text in pages):
        raise ValueError("it has no text GridLens can extract; it may be a scanned image, which needs OCR first")
    return (title if 0 < len(title) <= 120 else path.stem), pages


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_write(path: Path, data: bytes) -> None:
    """Write a cache file in one step, readable only by the user."""
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)


def _index_folder(folder: Path) -> Path:
    index = folder / INDEX_FOLDER
    if index.is_symlink():
        raise AgentError("UNSAFE_PATH", f"{index} is a symbolic link; remove it so GridLens can write its cache there.")
    index.mkdir(mode=0o700, exist_ok=True)
    return index


def document_files(folder: Path) -> tuple[list[Path], list[str]]:
    """Return the readable documents under folder, sorted, and a sentence for each file left out."""
    files, skipped = [], []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if INDEX_FOLDER in relative.parts or any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in SUFFIXES:
            skipped.append(f"{relative}: GridLens reads PDF, text, Markdown, and HTML files only.")
        elif path.stat().st_size > MAX_FILE_BYTES:
            skipped.append(f"{relative}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        else:
            files.append(path)
    if len(files) > MAX_DOCUMENTS:
        skipped.append(f"Only the first {MAX_DOCUMENTS:,} of {len(files):,} documents, by name, are searched.")
        files = files[:MAX_DOCUMENTS]
    return files, skipped


def load_library(folder: Path) -> Library:
    """Read every document in folder, from the cache when a file has not changed since it was read."""
    index = _index_folder(folder)
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
            entry = {"size": info.st_size, "mtime_ns": info.st_mtime_ns, "sha256": _sha256(path)}
        known[relative] = entry
        cached = index / f"{entry['sha256']}.json"
        record = None
        if cached.is_file():
            try:
                record = json.loads(cached.read_text(encoding="utf-8"))
            except ValueError:
                record = None
        if record is None:
            try:
                title, pages = extract(path)
            except ValueError as exc:
                problems.append(f"{relative}: {exc}.")
                record = {"error": str(exc)}
            else:
                record = {"title": title, "pages": pages}
            _private_write(cached, json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if "error" in record:
            if f"{relative}: {record['error']}." not in problems:
                problems.append(f"{relative}: {record['error']}.")
            continue
        pages = [(page, label, text) for page, label, text in record["pages"]]
        found = split_passages(record["title"], relative, pages)
        documents.append({"document": record["title"], "file": relative, "path": str(path), "pages": sum(1 for page, _, _ in pages if page is not None), "passages": len(found), "sha256": entry["sha256"]})
        passages.extend(found)
    if known != manifest["files"]:
        _private_write(manifest_path, json.dumps({"version": INDEX_VERSION, "files": known}, indent=2).encode("utf-8"))
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


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def passage_embeddings(library: Library, endpoint: str, model: str) -> list[list[float]]:
    """Return a unit embedding of every passage, computing only those of documents not embedded before."""
    index = _index_folder(library.folder)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
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
        found = [_unit(vector) for vector in _embed(endpoint, model, [f"{passage.document} {passage.section}\n{passage.text}" for passage in passages])]
        _private_write(path, array("f", [value for vector in found for value in vector]).tobytes())
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
    (query_vector,) = [_unit(vector) for vector in _embed(local_endpoint(endpoint), model, [query])]
    similarity = [sum(a * b for a, b in zip(query_vector, lookup[id(passage)])) for passage in passages]
    top_lexical = max(lexical, default=0.0) or 1.0
    low, high = min(similarity, default=0.0), max(similarity, default=0.0)
    spread = (high - low) or 1.0
    scored = [
        (passage, HYBRID_WEIGHT * lexical_score / top_lexical + (1 - HYBRID_WEIGHT) * (close - low) / spread, lexical_score, close)
        for passage, lexical_score, close in zip(passages, lexical, similarity)
    ]
    scored.sort(key=lambda item: -item[1])
    return scored, f"BM25 and {model} embeddings, each scaled to 0 to 1 over the passages searched, averaged"
