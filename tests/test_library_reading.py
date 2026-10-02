"""Reading reference documents: files, text, pages, and passages."""
from __future__ import annotations

import pytest

from gridlens.agent.library import cache, reading


STANDARD_TITLE = "TPL-001-5.1 Transmission System Planning Performance"


def test_headings_are_found_by_pattern():
    lines = (
        "R2.1.4. For each of the studies",
        "R1. Each Transmission Planner and Planning Coordinator shall "
        "maintain System models within its respective area for performing "
        "its studies.",
        "4.1. Functional Entities:",
        "B. Requirements and Measures",
        "Table 1 – Steady State Performance",
        "## Scope",
        "M3. Each Planning Coordinator",
        "The Planning Coordinator shall, within 30 days, do things.",
        "Page 3 of 24",
        "Rate B applies after a contingency.",
    )
    expected = [
        "R2.1.4", "R1", "4.1. Functional Entities:",
        "B. Requirements and Measures", "Table 1 – Steady State Performance",
        "Scope", "M3", "", "", "",
    ]
    assert [reading.heading(line) for line in lines] == expected


def test_a_pdf_keeps_its_title_and_printed_page_labels(reference_library):
    title, pages = reading.extract(reference_library / "TPL-001-5.1.pdf")
    assert title == STANDARD_TITLE
    assert [(page, label) for page, label, __ in pages] == [(1, "5"), (2, "6")]
    assert "Rate B applies" in pages[0][2]


def test_a_pdf_read_in_page_ranges_matches_reading_it_whole(
    make_pdf, tmp_path
):
    path = tmp_path / "long.pdf"
    path.write_bytes(make_pdf([[f"Page {n} text."] for n in range(1, 8)]))
    outline = reading.pdf_outline(path)
    texts = reading.pdf_page_texts(path, 0, 3)
    texts += reading.pdf_page_texts(path, 3, 7)
    assert outline == reading.PdfOutline("", ("1", "2", "3", "4", "5", "6",
                                              "7"))
    assert reading.assemble_pdf(path, outline, texts) == reading.extract(path)
    assert reading.extract(path)[0] == "long"


def test_html_text_keeps_its_title_and_headings_but_not_scripts(
    reference_library
):
    title, pages = reading.extract(reference_library / "guide.html")
    ((page, label, text),) = pages
    assert (title, page, label) == ("Operating guide", None, "")
    assert "## Voltage" in text and "0.95 to 1.05 pu" in text
    assert "var x" not in text


def test_unreadable_pdfs_raise_a_sentence_for_the_user(
    reference_library, tmp_path
):
    with pytest.raises(ValueError, match="no text GridLens can extract"):
        reading.extract(reference_library / "scanned.pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 not really a PDF")
    with pytest.raises(ValueError, match="could not be read as a PDF"):
        reading.pdf_outline(broken)
    with pytest.raises(ValueError, match="could not be read as a PDF"):
        reading.pdf_page_texts(broken, 0, 1)


def test_passages_keep_the_page_label_and_carry_the_section_over(
    reference_library
):
    title, pages = reading.extract(reference_library / "TPL-001-5.1.pdf")
    passages = reading.split_passages(title, "TPL-001-5.1.pdf", pages)
    places = [(item.page, item.page_label, item.section) for item in passages]
    assert places == [(1, "5", "R1"), (2, "6", "R2")]
    assert {item.document for item in passages} == {STANDARD_TITLE}


def test_a_long_page_splits_into_passages_of_at_most_passage_chars():
    text = "\n".join(f"Line {n} of the planning criteria." for n in range(99))
    passages = reading.split_passages("Criteria", "c.txt", [(None, "", text)])
    assert len(passages) > 1
    assert all(len(item.text) <= reading.PASSAGE_CHARS for item in passages)
    assert "\n".join(item.text for item in passages) == text


def test_document_files_leave_out_hidden_cached_and_unsupported_files(
    reference_library
):
    (reference_library / ".hidden.pdf").write_bytes(b"%PDF")
    index = cache.index_folder(reference_library)
    (index / "cached.txt").write_text("cached text")
    link = reference_library / "link.md"
    link.symlink_to(reference_library / "guide.html")
    files, skipped = reading.document_files(reference_library)
    found = [str(path.relative_to(reference_library)) for path in files]
    assert found == [
        "TPL-001-5.1.pdf", "criteria/planning_criteria.md", "guide.html",
        "scanned.pdf",
    ]
    assert skipped == [
        "notes.docx: GridLens reads PDF, text, Markdown, and HTML files only."
    ]


def test_document_files_name_what_is_too_large_or_past_the_limit(
    reference_library, monkeypatch
):
    monkeypatch.setattr(reading, "MAX_FILE_BYTES", 200)
    monkeypatch.setattr(reading, "MAX_DOCUMENTS", 1)
    files, skipped = reading.document_files(reference_library)
    assert [path.name for path in files] == ["planning_criteria.md"]
    assert "TPL-001-5.1.pdf: larger than 0 MB." in skipped
    assert skipped[-1] == (
        "Only the first 1 of 2 documents, by name, are searched."
    )
