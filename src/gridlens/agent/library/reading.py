"""Reading reference documents: their files, text, and passages.

GridLens reads the PDF, plain text, Markdown, and HTML files in a
Reference documents folder and sends them nowhere. Each file's text is
split into passages that keep their document, page, and section, so an
answer can cite "TPL-001-5.1, page 7, R2.1".

A page number is the PDF's own page, and a page label is the number
printed on the page when the PDF records one. A section is the nearest
heading above the passage, found by pattern (numbered headings, NERC
requirement and measure IDs such as R2.1, lettered parts such as
"B. Requirements and Measures", tables and attachments, and Markdown
headings), so it is a best guess that a reader should check.

A long PDF can be read in parts: `pdf_outline` gives its title and the
label of every page, and `pdf_page_texts` the text of a range of its
pages, so several processes can read one PDF at once.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from html.parser import HTMLParser
import logging
from pathlib import Path
import re

from gridlens.agent.library import cache


SUFFIXES = {
    ".pdf": "pdf", ".txt": "text", ".md": "markdown",
    ".markdown": "markdown", ".html": "html", ".htm": "html",
}
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_DOCUMENTS = 1000
PASSAGE_CHARS = 1200
# A heading this close to the start of a passage starts a new passage
# instead of joining the last one.
MIN_PASSAGE_CHARS = 200
MAX_HEADING_CHARS = 120
MAX_TITLE_CHARS = 120
# A requirement or measure, such as "R2.1. Each Planning Coordinator
# shall ...", begins a section however long its line.
_REQUIREMENT = re.compile(r"^(?P<text>[RM]\d+(?:\.\d+)*)\.?(?:\s+[A-Z(].*)?$")
_HEADINGS = (
    re.compile(r"^#{1,6}\s+(?P<text>.{1,100})$"),
    re.compile(r"^(?P<text>[A-H]\.\s+[A-Z][A-Za-z,&/ -]{2,70})$"),
    re.compile(
        r"^(?P<text>(?:Attachment|Appendix|Table|Section|Part|Chapter"
        r"|Exhibit)\s+[0-9A-Z]+(?:\.\d+)*\b[^.;]{0,80})$"
    ),
    re.compile(r"^(?P<text>\d+(?:\.\d+){0,4}\.?\s+[A-Z][^.;,]{1,80})$"),
)
_BLANK_LINES = re.compile(r"\n\s*\n+")


@dataclass(frozen=True)
class Passage:
    """One passage of a document and where it is.

    page is the PDF's page number (None for a text, Markdown, or HTML
    file), page_label the number printed on that page, and section the
    nearest heading above the passage.
    """

    document: str
    file: str
    page: int | None
    page_label: str
    section: str
    text: str


@dataclass(frozen=True)
class PdfOutline:
    """A PDF's title and the printed label of each of its pages."""

    title: str
    labels: tuple[str, ...]


def heading(line: str) -> str:
    """Return the section a line begins, or "" for ordinary text."""
    text = " ".join(line.split())
    requirement = _REQUIREMENT.match(text)
    found = requirement.group("text") if requirement else ""
    if not found and text and len(text) <= MAX_HEADING_CHARS:
        for pattern in _HEADINGS:
            match = pattern.match(text)
            if match:
                found = match.group("text").strip()
                break
    return found


def split_passages(
    document: str, file: str, pages: list[tuple[int | None, str, str]]
) -> list[Passage]:
    """Split a document's pages into passages that start at headings.

    pages holds (page number, page label, text). A passage holds about
    PASSAGE_CHARS characters and never crosses a page. A section
    carries over from page to page until the next heading.
    """
    passages = []
    section = ""
    for number, label, text in pages:
        lines: list[str] = []
        size = 0
        start_section = section
        # While a passage holds only headings, it takes the latest,
        # most specific one as its section.
        headings_only = True
        for raw in text.splitlines():
            line = raw.rstrip()
            found = heading(line)
            if found and size >= MIN_PASSAGE_CHARS:
                _add_passage(passages, lines, document, file, number,
                             label, start_section)
                lines, size, headings_only = [], 0, True
            if found:
                section = found
                if headings_only:
                    start_section = section
            if size + len(line) > PASSAGE_CHARS and lines:
                _add_passage(passages, lines, document, file, number,
                             label, start_section)
                lines, size, headings_only = [], 0, True
                start_section = section
            lines.append(line)
            size += len(line) + 1
            if line.strip() and not found:
                headings_only = False
        _add_passage(passages, lines, document, file, number, label,
                     start_section)
    return passages


def _add_passage(
    passages: list[Passage], lines: list[str], document: str, file: str,
    page: int | None, label: str, section: str,
) -> None:
    """Append the passage these lines make, unless they are blank."""
    body = "\n".join(lines).strip()
    if body:
        passages.append(Passage(document, file, page, label, section, body))


class _HTMLText(HTMLParser):
    """Collect the text of an HTML page, a line per block."""

    BLOCKS = frozenset({
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "table", "title",
    })
    HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
    SKIPPED = ("script", "style")

    def __init__(self) -> None:
        """Start with no text, outside the title and any script."""
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        """Open a block, a heading, the title, or a skipped element."""
        if tag in self.SKIPPED:
            self.skipping += 1
        if tag == "title":
            self.in_title = True
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag in self.HEADINGS:
            self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        """Close a block, the title, or a skipped element."""
        if tag in self.SKIPPED and self.skipping:
            self.skipping -= 1
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        """Keep text, unless it is inside a script or a style."""
        if self.in_title:
            self.title += data
        elif not self.skipping:
            self.parts.append(data)


def extract(path: Path) -> tuple[str, list[tuple[int | None, str, str]]]:
    """Return a file's title and its pages as (page, label, text).

    A text, Markdown, or HTML file is one page with no number. Raises
    ValueError, with a sentence for the user, when the file cannot be
    read.
    """
    kind = SUFFIXES[path.suffix.lower()]
    if kind == "pdf":
        title, pages = _extract_pdf(path)
    elif kind == "html":
        title, pages = _extract_html(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        title, pages = path.stem, [(None, "", text)]
    return title, pages


def _extract_html(path: Path) -> tuple[str, list[tuple[None, str, str]]]:
    """Return an HTML page's title and its text as one page."""
    parser = _HTMLText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    body = _BLANK_LINES.sub("\n\n", "".join(parser.parts))
    title = " ".join(parser.title.split()) or path.stem
    return title, [(None, "", body)]


def _extract_pdf(path: Path) -> tuple[str, list[tuple[int, str, str]]]:
    """Return a PDF's title and every page, reading the file once."""
    with _pdf_failures():
        reader = _open_pdf(path)
        outline = _outline(reader)
        texts = _page_texts(reader, 0, len(outline.labels))
    return assemble_pdf(path, outline, texts)


@contextlib.contextmanager
def _pdf_failures():
    """Turn a failure to read a PDF into a ValueError for the user.

    pypdf is imported here and in `_open_pdf`, not with the module, so
    a process that never reads a PDF never loads it.
    """
    from pypdf.errors import PyPdfError

    try:
        yield
    except (PyPdfError, OSError, KeyError, TypeError, ValueError,
            AttributeError, IndexError, NotImplementedError,
            RecursionError) as exc:
        raise ValueError(f"it could not be read as a PDF ({exc})") from exc


def _open_pdf(path: Path):
    """Open a PDF with pypdf, decrypting one that has no password."""
    import pypdf

    # pypdf logs what it skips in a malformed page; the text it
    # returns is what matters here.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = pypdf.PdfReader(str(path))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("it is encrypted with a password")
    return reader


def _outline(reader) -> PdfOutline:
    """Return the outline of a PDF a pypdf reader has open."""
    recorded = list(reader.page_labels)
    labels = tuple(
        recorded[index] if index < len(recorded) else str(index + 1)
        for index in range(len(reader.pages))
    )
    title = str((reader.metadata or {}).get("/Title") or "").strip()
    return PdfOutline(title, labels)


def _page_texts(reader, start: int, stop: int) -> list[str]:
    """Return the text of pages start up to stop of an open PDF."""
    return [
        reader.pages[index].extract_text() or ""
        for index in range(start, stop)
    ]


def pdf_outline(path: Path) -> PdfOutline:
    """Return a PDF's title and the printed label of every page.

    A page with no printed label is labelled with its page number.
    Raises ValueError, with a sentence for the user, when the file
    cannot be read as a PDF.
    """
    with _pdf_failures():
        outline = _outline(_open_pdf(path))
    return outline


def pdf_page_texts(path: Path, start: int, stop: int) -> list[str]:
    """Return the text of a PDF's pages from start up to stop.

    Pages are counted from 0. Raises ValueError, with a sentence for
    the user, when the file cannot be read as a PDF.
    """
    with _pdf_failures():
        texts = _page_texts(_open_pdf(path), start, stop)
    return texts


def assemble_pdf(
    path: Path, outline: PdfOutline, texts: list[str]
) -> tuple[str, list[tuple[int | None, str, str]]]:
    """Return a PDF's title and pages from its outline and page texts.

    The title is the PDF's own when it records a short one, else the
    file name. Raises ValueError when no page has text.
    """
    if not any(text.strip() for text in texts):
        raise ValueError(
            "it has no text GridLens can extract; it may be a scanned "
            "image, which needs OCR first"
        )
    pages = [
        (number, label, text)
        for number, (label, text) in enumerate(zip(outline.labels, texts),
                                               start=1)
    ]
    title = outline.title
    if not 0 < len(title) <= MAX_TITLE_CHARS:
        title = path.stem
    return title, pages


def document_files(folder: Path) -> tuple[list[Path], list[str]]:
    """Return the readable documents under folder, sorted by path.

    Also returns a sentence for each file left out. Hidden files, the
    cache folder, symbolic links, unsupported types, and files larger
    than MAX_FILE_BYTES are left out, and so is every document past
    the first MAX_DOCUMENTS.
    """
    files, skipped = [], []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        hidden = any(part.startswith(".") for part in relative.parts)
        if hidden or cache.INDEX_FOLDER in relative.parts:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in SUFFIXES:
            skipped.append(
                f"{relative}: GridLens reads PDF, text, Markdown, and "
                "HTML files only."
            )
        elif path.stat().st_size > MAX_FILE_BYTES:
            megabytes = MAX_FILE_BYTES // (1024 * 1024)
            skipped.append(f"{relative}: larger than {megabytes} MB.")
        else:
            files.append(path)
    if len(files) > MAX_DOCUMENTS:
        skipped.append(
            f"Only the first {MAX_DOCUMENTS:,} of {len(files):,} "
            "documents, by name, are searched."
        )
        files = files[:MAX_DOCUMENTS]
    return files, skipped
