from __future__ import annotations

from pathlib import Path

from gridpack_workbench.analysis.parsers import sniff_table


def test_sniff_table_returns_empty_list_for_missing_file(tmp_path: Path) -> None:
    assert sniff_table(tmp_path / "missing.txt") == []


def test_sniff_table_reads_comma_delimited_rows(tmp_path: Path) -> None:
    table = tmp_path / "table.csv"
    table.write_text("name,value\nalpha,1\nbeta,2\n", encoding="utf-8")

    assert sniff_table(table) == [["name", "value"], ["alpha", "1"], ["beta", "2"]]


def test_sniff_table_falls_back_to_whitespace_rows(tmp_path: Path) -> None:
    table = tmp_path / "table.txt"
    table.write_text("row value status\n1 2 ok\n", encoding="utf-8")

    assert sniff_table(table) == [["row", "value", "status"], ["1", "2", "ok"]]


def test_sniff_table_honors_max_rows(tmp_path: Path) -> None:
    table = tmp_path / "table.csv"
    table.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    assert sniff_table(table, max_rows=2) == [["a", "b"], ["1", "2"]]
