from __future__ import annotations

from gridlens.analysis.parser_models import OutputFile
from gridlens.gui.results_view_models import (
    format_file_size,
    output_file_row,
    output_file_rows,
    read_run_status,
    run_list_label,
)


def test_read_run_status_handles_missing_invalid_and_valid_status(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    assert read_run_status(run_dir) == "not started"

    (run_dir / "status.json").write_text("{not json", encoding="utf-8")
    assert read_run_status(run_dir) == "unknown"

    (run_dir / "status.json").write_text('{"status": "completed"}', encoding="utf-8")
    assert read_run_status(run_dir) == "completed"


def test_run_list_label_uses_folder_name_and_status(tmp_path) -> None:
    run_dir = tmp_path / "2026-06-17_12-00-00"

    assert run_list_label(run_dir, "failed") == "2026-06-17_12-00-00    failed"


def test_output_file_rows_match_results_table_columns() -> None:
    output = OutputFile(
        file_name="success.txt",
        relative_path="work/success.txt",
        size_bytes=123,
        suffix=".txt",
    )

    row = output_file_row(output)

    assert row == {
        "File": "success.txt",
        "Path": "work/success.txt",
        "Size": "123 B",
        "Type": ".txt",
    }
    assert output_file_rows([output]) == [row]


def test_file_sizes_are_shown_in_the_largest_unit_they_reach() -> None:
    assert [format_file_size(size) for size in (0, 1023, 1024, 1536, 5 * 1024**2, 3 * 1024**3, 2 * 1024**4)] == [
        "0 B", "1,023 B", "1.0 KB", "1.5 KB", "5.0 MB", "3.0 GB", "2.0 TB",
    ]
