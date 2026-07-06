from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from gridlens.analysis.parser_models import OutputFile


OUTPUT_TABLE_COLUMNS = ["File", "Path", "Size", "Type"]


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


def output_file_row(output: OutputFile) -> dict[str, object]:
    return {
        "File": output.file_name,
        "Path": output.relative_path,
        "Size": output.size_bytes,
        "Type": output.suffix,
    }


def output_file_rows(outputs: Iterable[OutputFile]) -> list[dict[str, object]]:
    return [output_file_row(output) for output in outputs]


__all__ = [
    "OUTPUT_TABLE_COLUMNS",
    "output_file_row",
    "output_file_rows",
    "read_run_status",
    "run_list_label",
]
