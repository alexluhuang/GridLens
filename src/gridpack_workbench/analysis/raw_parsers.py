from __future__ import annotations

import csv
from pathlib import Path

from gridpack_workbench.analysis.parser_models import ParsedTable


BUS_METADATA_COLUMNS = ["bus_id", "bus_name", "base_kv", "area", "zone", "owner", "vm", "va"]
BRANCH_METADATA_COLUMNS = [
    "from_bus",
    "to_bus",
    "line_id",
    "r",
    "x",
    "b",
    "ratea",
    "rateb",
    "ratec",
    "gi",
    "bi",
    "gj",
    "bj",
    "status",
    "metered_end",
    "length",
    "owner_1",
    "owner_1_fraction",
    "raw_branch_type",
]


def parse_raw_bus_metadata(run_dir: str | Path, raw_file_name: str = "training.raw") -> ParsedTable:
    """Parse PSS/E RAW bus rows needed for downstream enrichment."""
    path = Path(run_dir) / "work" / raw_file_name
    if not path.exists():
        return ParsedTable(
            "bus_metadata",
            raw_file_name,
            BUS_METADATA_COLUMNS,
            notes=[f"{raw_file_name} was not found."],
        )

    rows: list[dict[str, object]] = []
    bus_started = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        parsed = _parse_raw_csv_line(line)
        if not parsed:
            continue

        first = parsed[0].strip()
        if first == "0" and bus_started:
            break
        if first == "0":
            continue
        if len(parsed) < 9:
            if bus_started:
                break
            continue

        try:
            row = {
                "bus_id": int(first),
                "bus_name": _clean_raw_string(parsed[1]),
                "base_kv": float(parsed[2]),
                "area": int(parsed[4]),
                "zone": int(parsed[5]),
                "owner": int(parsed[6]),
                "vm": float(parsed[7]),
                "va": float(parsed[8]),
            }
        except (ValueError, IndexError):
            if bus_started:
                break
            continue
        rows.append(row)
        bus_started = True

    notes = []
    if not rows:
        notes.append("No PSS/E bus metadata records were parsed.")
    return ParsedTable("bus_metadata", raw_file_name, BUS_METADATA_COLUMNS, rows, notes)


def parse_raw_branch_metadata(run_dir: str | Path, raw_file_name: str = "training.raw") -> ParsedTable:
    """Parse PSS/E RAW non-transformer branch records used in the branch master export."""
    path = Path(run_dir) / "work" / raw_file_name
    if not path.exists():
        return ParsedTable(
            "branch_metadata",
            raw_file_name,
            BRANCH_METADATA_COLUMNS,
            notes=[f"{raw_file_name} was not found."],
        )

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, object]] = []
    in_branch_section = False
    rejected = 0

    for line in lines:
        upper = line.upper()
        if "BEGIN BRANCH DATA" in upper or "BEGIN NONTRANSFORMER BRANCH DATA" in upper:
            in_branch_section = True
            continue
        if in_branch_section and ("END OF BRANCH DATA" in upper or "END OF NONTRANSFORMER BRANCH DATA" in upper):
            break
        if not in_branch_section:
            continue

        parsed = _parse_raw_csv_line(line)
        if not parsed or len(parsed) < 18:
            rejected += 1
            continue

        try:
            rows.append(
                {
                    "from_bus": abs(int(float(parsed[0]))),
                    "to_bus": abs(int(float(parsed[1]))),
                    "line_id": _clean_raw_string(parsed[2]),
                    "r": _optional_float(parsed, 3),
                    "x": _optional_float(parsed, 4),
                    "b": _optional_float(parsed, 5),
                    "ratea": _optional_float(parsed, 6),
                    "rateb": _optional_float(parsed, 7),
                    "ratec": _optional_float(parsed, 8),
                    "gi": _optional_float(parsed, 9),
                    "bi": _optional_float(parsed, 10),
                    "gj": _optional_float(parsed, 11),
                    "bj": _optional_float(parsed, 12),
                    "status": _optional_int(parsed, 13),
                    "metered_end": _optional_int(parsed, 14),
                    "length": _optional_float(parsed, 15),
                    "owner_1": _optional_int(parsed, 16),
                    "owner_1_fraction": _optional_float(parsed, 17),
                    "raw_branch_type": "nontransformer_branch",
                }
            )
        except (ValueError, IndexError):
            rejected += 1

    notes = []
    if rejected:
        notes.append(
            f"Rejected {rejected} RAW branch lines that did not match the expected nontransformer branch schema."
        )
    if not rows:
        notes.append("No nontransformer branch records were parsed from the RAW file.")
    return ParsedTable("branch_metadata", raw_file_name, BRANCH_METADATA_COLUMNS, rows, notes)


def _parse_raw_csv_line(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("@"):
        return []
    try:
        return [part.strip() for part in next(csv.reader([line], skipinitialspace=True))]
    except csv.Error:
        return []


def _clean_raw_string(value: str) -> str:
    return value.strip().strip("'").strip('"').strip()


def _optional_float(values: list[str], index: int) -> float | None:
    if index >= len(values) or values[index].strip() == "":
        return None
    return float(values[index])


def _optional_int(values: list[str], index: int) -> int | None:
    value = _optional_float(values, index)
    return int(value) if value is not None else None


__all__ = [
    "BRANCH_METADATA_COLUMNS",
    "BUS_METADATA_COLUMNS",
    "parse_raw_branch_metadata",
    "parse_raw_bus_metadata",
]
