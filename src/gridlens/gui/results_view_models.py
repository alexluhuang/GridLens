from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from gridlens.analysis.parser_models import OutputFile


OUTPUT_TABLE_COLUMNS = ["File", "Path", "Size", "Type"]
SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def read_run_status(run_dir: str | Path) -> str:
    status_file = Path(run_dir) / "status.json"
    if not status_file.exists():
        return "not started"
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    return str(data.get("status") or "unknown")


def run_list_label(run_dir: str | Path, status: str) -> str:
    return f"{Path(run_dir).name}    {status}"


def format_file_size(size_bytes: int) -> str:
    """Return a file size in the largest unit it reaches, counting 1 KB as 1,024 bytes."""
    size = float(size_bytes)
    for unit in SIZE_UNITS[:-1]:
        if abs(size) < 1024:
            break
        size /= 1024
    else:
        unit = SIZE_UNITS[-1]
    if unit == "B":
        return f"{int(size):,} B"
    return f"{size:,.1f} {unit}"


def output_file_row(output: OutputFile) -> dict[str, object]:
    return {
        "File": output.file_name,
        "Path": output.relative_path,
        "Size": format_file_size(output.size_bytes),
        "Type": output.suffix,
    }


def output_file_rows(outputs: Iterable[OutputFile]) -> list[dict[str, object]]:
    return [output_file_row(output) for output in outputs]


__all__ = [
    "OUTPUT_TABLE_COLUMNS",
    "format_file_size",
    "output_file_row",
    "output_file_rows",
    "read_run_status",
    "run_list_label",
]
