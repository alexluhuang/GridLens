from __future__ import annotations

from dataclasses import dataclass, field


PARSER_VERSION = "2026.07.05"


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


@dataclass(slots=True)
class ParsedTable:
    name: str
    source_file: str
    columns: list[str]
    rows: list[dict[str, object]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def schema_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source_file": self.source_file,
            "columns": self.columns,
            "row_count": self.row_count,
            "notes": self.notes,
            "parser_version": PARSER_VERSION,
        }


__all__ = ["OutputFile", "PARSER_VERSION", "ParsedTable", "SuccessSummary"]
