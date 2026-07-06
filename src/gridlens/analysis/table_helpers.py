from __future__ import annotations

from collections.abc import Sequence

from gridlens.analysis.parser_models import ParsedTable


def append_missing_columns(table: ParsedTable, columns: Sequence[str]) -> None:
    """Append columns to a parsed table schema without duplicating names."""
    for column in columns:
        if column not in table.columns:
            table.columns.append(column)


def take_fields(row: dict[str, object], fields: Sequence[str]) -> dict[str, object]:
    """Return a copy of the requested fields that exist in a parsed row."""
    return {field: row.get(field, "") for field in fields if field in row}


def as_float(value: object) -> float | None:
    """Parse numeric table values while treating blanks as missing data."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def float_or_zero(value: object) -> float:
    """Parse a numeric value, returning zero for missing or invalid data."""
    parsed = as_float(value)
    return parsed if parsed is not None else 0.0


def pct(value: int, total: int) -> float:
    """Return a rounded percentage, guarding against division by zero."""
    if not total:
        return 0.0
    return round(value / total * 100, 4)


def cell_value(value: object) -> object:
    """Normalize values before writing parsed data to CSV."""
    if value is None:
        return ""
    return value
