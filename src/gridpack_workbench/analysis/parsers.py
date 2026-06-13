from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
import re


@dataclass(slots=True)
class OutputFile:
    file_name: str
    relative_path: str
    size_bytes: int
    suffix: str


@dataclass(slots=True)
class SuccessSummary:
    exists: bool
    file_name: str
    success_count: int = 0
    failure_count: int = 0
    unknown_count: int = 0
    total_count: int = 0
    note: str = ""


def list_output_files(run_dir: str | Path) -> list[OutputFile]:
    run_path = Path(run_dir)
    work_dir = run_path / "work"
    if not work_dir.exists():
        return []

    files = []
    for path in sorted(work_dir.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            OutputFile(
                file_name=path.name,
                relative_path=str(path.relative_to(run_path)),
                size_bytes=path.stat().st_size,
                suffix=path.suffix.lower(),
            )
        )
    return files


def find_success_file(run_dir: str | Path) -> Path | None:
    work_dir = Path(run_dir) / "work"
    candidates = [
        work_dir / "success.txt",
        work_dir / "success",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(work_dir.glob("*success*"))
    return matches[0] if matches else None


def summarize_success_file(run_dir: str | Path) -> SuccessSummary:
    success_file = find_success_file(run_dir)
    if not success_file:
        return SuccessSummary(False, "", note="No success file was found in the run work directory.")

    text = success_file.read_text(encoding="utf-8", errors="replace")
    tokens = re.findall(r"\b(true|false|success|failed|fail|pass|passed|0|1)\b", text, flags=re.IGNORECASE)
    success_values = {"true", "success", "pass", "passed", "1"}
    failure_values = {"false", "failed", "fail", "0"}

    success_count = 0
    failure_count = 0
    unknown_count = 0
    for token in tokens:
        value = token.lower()
        if value in success_values:
            success_count += 1
        elif value in failure_values:
            failure_count += 1
        else:
            unknown_count += 1

    return SuccessSummary(
        exists=True,
        file_name=success_file.name,
        success_count=success_count,
        failure_count=failure_count,
        unknown_count=unknown_count,
        total_count=success_count + failure_count + unknown_count,
        note="Counts are token-based until exact GridPACK output schemas are configured.",
    )


def sniff_table(path: str | Path, max_rows: int = 20) -> list[list[str]]:
    table_path = Path(path)
    if not table_path.exists() or not table_path.is_file():
        return []

    text = table_path.read_text(encoding="utf-8", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = "," if "," in sample else None  # type: ignore[attr-defined]

    rows = []
    if getattr(dialect, "delimiter", None):
        reader = csv.reader(text.splitlines(), dialect)
        for row in reader:
            rows.append(row)
            if len(rows) >= max_rows:
                break
        return rows

    for line in text.splitlines()[:max_rows]:
        rows.append(line.split())
    return rows
