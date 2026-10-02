"""The passage index: passages and their words, in SQLite."""
from __future__ import annotations

from collections import Counter
import contextlib
import math
import stat

import pytest

from gridlens.agent.library import index, reading
from gridlens.agent.library.reading import Passage


QUERIES = (
    "Rate B after a contingency",
    "steady state voltage limits",
    "TPL-001 planning coordinator",
    "P1 single contingency events",
    "transfer capability",
)


def scan_bm25(passages: list[Passage], query: str) -> list[float]:
    """Score every passage by reading all of them, as before."""
    wanted = list(dict.fromkeys(index.tokens(query)))
    counts = [
        Counter(index.tokens(f"{item.section}\n{item.text}"))
        for item in passages
    ]
    lengths = [sum(count.values()) for count in counts]
    average = sum(lengths) / len(lengths) or 1.0
    total = len(passages)
    frequency = {
        term: sum(1 for count in counts if term in count) for term in wanted
    }
    scores = []
    for count, length in zip(counts, lengths):
        score = 0.0
        for term in wanted:
            seen = count.get(term, 0)
            if not seen:
                continue
            inverse = math.log(
                1 + (total - frequency[term] + 0.5) / (frequency[term] + 0.5)
            )
            score += inverse * seen * (index.BM25_K1 + 1) / (
                seen + index.BM25_K1
                * (1 - index.BM25_B + index.BM25_B * length / average)
            )
        scores.append(score)
    return scores


def library_passages(folder) -> dict[str, list[Passage]]:
    """Return the passages of each readable file in a folder."""
    files, __ = reading.document_files(folder)
    found = {}
    for path in files:
        try:
            title, pages = reading.extract(path)
        except ValueError:
            continue
        found[path.name] = reading.split_passages(title, path.name, pages)
    return found


@pytest.fixture
def indexed(reference_library):
    """Index the readable documents of the reference library.

    Yields the open index, the indexed documents by file name, and
    their passages by file name.
    """
    passages = library_passages(reference_library)
    connection = index.open_for_writing(reference_library)
    for name, found in passages.items():
        index.add_document(connection, name, found[0].document, 0, found)
    documents = index.read_documents(connection)
    with contextlib.closing(connection):
        yield connection, documents, passages


def test_tokens_keep_identifiers_whole_and_in_parts():
    assert index.tokens("TPL-001-5.1 and the N-1 rule") == [
        "tpl-001-5.1", "tpl", "001", "5", "1", "n-1", "n", "1", "rule",
    ]


def test_bm25_from_the_postings_matches_a_scan_of_every_passage(indexed):
    connection, documents, passages = indexed
    names = sorted(passages)
    scope = [documents[name] for name in names]
    every = [item for name in names for item in passages[name]]
    for query in QUERIES:
        assert index.bm25(connection, scope, query).tolist() == (
            scan_bm25(every, query)
        )


def test_bm25_counts_a_document_twice_when_two_files_hold_it(indexed):
    connection, documents, passages = indexed
    scope = [documents["TPL-001-5.1.pdf"], documents["guide.html"],
             documents["TPL-001-5.1.pdf"]]
    every = (passages["TPL-001-5.1.pdf"] + passages["guide.html"]
             + passages["TPL-001-5.1.pdf"])
    for query in QUERIES:
        assert index.bm25(connection, scope, query).tolist() == (
            scan_bm25(every, query)
        )


def test_bm25_over_part_of_the_library_uses_that_parts_statistics(indexed):
    connection, documents, passages = indexed
    only = documents["planning_criteria.md"]
    scores = index.bm25(connection, [only], "Rate B")
    assert scores.tolist() == scan_bm25(passages["planning_criteria.md"],
                                        "Rate B")
    assert index.bm25(connection, [], "Rate B").size == 0
    assert index.bm25(connection, [only], "the of and").tolist() == [0.0]


def test_a_document_keeps_its_passages_and_their_word_counts(indexed):
    connection, documents, passages = indexed
    standard = documents["TPL-001-5.1.pdf"]
    stored = index.read_passages(connection, standard, "copy/TPL.pdf")
    original = passages["TPL-001-5.1.pdf"]
    assert [(item.page, item.page_label, item.section, item.text)
            for item in stored] == [
        (item.page, item.page_label, item.section, item.text)
        for item in original
    ]
    assert {item.file for item in stored} == {"copy/TPL.pdf"}
    assert standard.lengths.tolist() == [
        len(index.tokens(f"{item.section}\n{item.text}"))
        for item in original
    ]
    picked = index.read_passages(connection, standard, "t.pdf", [1, 0])
    assert [item.text for item in picked] == [original[1].text,
                                              original[0].text]


def test_a_document_is_indexed_once_and_a_failure_keeps_its_reason(indexed):
    connection, documents, passages = indexed
    found = passages["guide.html"]
    index.add_document(connection, "guide.html", "Again", 0, found)
    index.add_failure(connection, "scanned", "it has no text")
    index.add_failure(connection, "scanned", "another reason")
    again = index.read_documents(connection)
    assert again["guide.html"].title == documents["guide.html"].title
    assert (again["scanned"].error, again["scanned"].passages) == (
        "it has no text", 0
    )


def test_recording_files_replaces_which_file_holds_which_document(indexed):
    connection, __, __ = indexed
    first = [index.IndexedFile("a.pdf", 10, 1, "x"),
             index.IndexedFile("b.pdf", 20, 2, "y")]
    index.record_files(connection, first)
    index.record_files(connection, first[1:])
    assert index.read_files(connection) == {"b.pdf": first[1]}


def test_removed_documents_take_their_passages_and_postings(indexed):
    connection, documents, __ = indexed
    removed = index.remove_documents_except(connection, {"guide.html"})
    assert removed == 2
    assert set(index.read_documents(connection)) == {"guide.html"}
    key = documents["guide.html"].key
    for table in ("passages", "postings"):
        held = connection.execute(
            f"SELECT DISTINCT document FROM {table}"
        ).fetchall()
        assert held == [(key,)]


def test_the_index_is_private_and_rebuilt_for_another_schema(
    reference_library
):
    connection = index.open_for_writing(reference_library)
    index.add_failure(connection, "x", "unreadable")
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    path = index.database_path(reference_library)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert index.open_for_reading(reference_library) is None
    with contextlib.closing(index.open_for_writing(reference_library)) as db:
        assert index.read_documents(db) == {}
    with contextlib.closing(index.open_for_reading(reference_library)) as db:
        assert index.read_documents(db) == {}


def test_a_damaged_index_is_rebuilt_and_a_missing_one_is_not_read(
    reference_library
):
    assert index.open_for_reading(reference_library) is None
    path = index.database_path(reference_library)
    path.parent.mkdir()
    path.write_bytes(b"not a database" * 100)
    assert index.open_for_reading(reference_library) is None
    with contextlib.closing(index.open_for_writing(reference_library)) as db:
        assert index.read_files(db) == {}


def test_a_search_reads_while_a_document_is_being_written(
    indexed, reference_library
):
    connection, documents, __ = indexed
    reader = index.open_for_reading(reference_library)
    with contextlib.closing(reader):
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM documents WHERE sha256 = 'guide.html'"
        )
        # The writer's change is not committed, so the reader still
        # sees every document, and is not blocked.
        assert set(index.read_documents(reader)) == set(documents)
        connection.execute("ROLLBACK")
