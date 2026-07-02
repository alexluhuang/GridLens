from __future__ import annotations

from collections.abc import Iterable, Mapping
import csv
from pathlib import Path

from gridpack_workbench.analysis.parser_models import ParsedTable
from gridpack_workbench.analysis.utilization import (
    NONTRANSFORMER_BRANCH,
    THREE_WINDING_TRANSFORMER_BRANCH,
    TWO_WINDING_TRANSFORMER_BRANCH,
)


BUS_METADATA_COLUMNS = ["bus_id", "bus_name", "base_kv", "area", "zone", "owner", "vm", "va"]
AREA_METADATA_COLUMNS = ["area", "slack_bus", "pdes", "ptol", "area_name"]
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
    "transformer_name",
    "transformer_winding",
    "transformer_terminal_count",
    "transformer_internal_bus",
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


def parse_raw_branch_metadata(
    run_dir: str | Path,
    raw_file_name: str = "training.raw",
    branch_rows: Iterable[Mapping[str, object]] | None = None,
) -> ParsedTable:
    """Parse PSS/E RAW branch-like records used in the branch master export."""
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
    seen_keys: set[tuple[int | None, int | None, str]] = set()
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
            _append_unique_branch_row(
                rows,
                seen_keys,
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
                    "raw_branch_type": NONTRANSFORMER_BRANCH,
                },
            )
        except (ValueError, IndexError):
            rejected += 1

    transformer_rows, transformer_rejected = _parse_transformer_branch_rows(lines, branch_rows)
    rejected += transformer_rejected
    for row in transformer_rows:
        _append_unique_branch_row(rows, seen_keys, row)

    notes = []
    if rejected:
        notes.append(
            f"Rejected {rejected} RAW branch/transformer lines that did not match the expected schema."
        )
    if not rows:
        notes.append("No branch-like records were parsed from the RAW file.")
    return ParsedTable("branch_metadata", raw_file_name, BRANCH_METADATA_COLUMNS, rows, notes)


def parse_raw_area_metadata(run_dir: str | Path, raw_file_name: str = "training.raw") -> ParsedTable:
    """Parse PSS/E RAW area interchange rows for control-area labels."""
    path = Path(run_dir) / "work" / raw_file_name
    if not path.exists():
        return ParsedTable(
            "area_metadata",
            raw_file_name,
            AREA_METADATA_COLUMNS,
            notes=[f"{raw_file_name} was not found."],
        )

    rows: list[dict[str, object]] = []
    in_area_section = False
    rejected = 0

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        upper = line.upper()
        if "BEGIN AREA DATA" in upper or "BEGIN AREA INTERCHANGE DATA" in upper:
            in_area_section = True
            continue
        if in_area_section and ("END OF AREA DATA" in upper or "END OF AREA INTERCHANGE DATA" in upper):
            break
        if not in_area_section:
            continue

        parsed = _parse_raw_csv_line(line)
        if not parsed or len(parsed) < 5:
            rejected += 1
            continue

        try:
            rows.append(
                {
                    "area": int(float(parsed[0])),
                    "slack_bus": _optional_int(parsed, 1),
                    "pdes": _optional_float(parsed, 2),
                    "ptol": _optional_float(parsed, 3),
                    "area_name": _clean_raw_string(parsed[4]),
                }
            )
        except (ValueError, IndexError):
            rejected += 1

    notes = []
    if rejected:
        notes.append(f"Rejected {rejected} RAW area lines that did not match the expected area schema.")
    if not rows:
        notes.append("No area interchange records were parsed from the RAW file.")
    return ParsedTable("area_metadata", raw_file_name, AREA_METADATA_COLUMNS, rows, notes)


def _parse_transformer_branch_rows(
    lines: list[str],
    branch_rows: Iterable[Mapping[str, object]] | None,
) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    rejected = 0
    raw_bus_ids = _raw_bus_ids(lines)
    observed_rows = _observed_branch_rows(branch_rows)
    observed_keys = {_branch_key(row): row for row in observed_rows}

    in_transformer_section = False
    index = 0
    while index < len(lines):
        upper = lines[index].upper()
        if "BEGIN TRANSFORMER DATA" in upper:
            in_transformer_section = True
            index += 1
            continue
        if in_transformer_section and "END OF TRANSFORMER DATA" in upper:
            break
        if not in_transformer_section:
            index += 1
            continue

        line_1 = _parse_raw_csv_line(lines[index])
        if not line_1:
            index += 1
            continue
        if len(line_1) < 4:
            rejected += 1
            index += 1
            continue

        try:
            i_bus = abs(int(float(line_1[0])))
            j_bus = abs(int(float(line_1[1])))
            k_bus = abs(int(float(line_1[2])))
            circuit_id = _clean_raw_string(line_1[3])
        except (ValueError, IndexError):
            rejected += 1
            index += 1
            continue

        if k_bus == 0:
            if index + 3 >= len(lines):
                rejected += 1
                break
            impedance_line = _parse_raw_csv_line(lines[index + 1])
            winding_line = _parse_raw_csv_line(lines[index + 2])
            if len(impedance_line) < 2 or len(winding_line) < 6:
                rejected += 1
                index += 4
                continue
            from_bus, to_bus = _observed_two_winding_endpoints(i_bus, j_bus, circuit_id, observed_keys)
            rows.append(
                _transformer_metadata_row(
                    line_1,
                    winding_line,
                    from_bus=from_bus,
                    to_bus=to_bus,
                    line_id=circuit_id,
                    raw_branch_type=TWO_WINDING_TRANSFORMER_BRANCH,
                    transformer_winding="1-2",
                    transformer_terminal_count=2,
                    impedance_line=impedance_line,
                )
            )
            index += 4
            continue

        if index + 3 >= len(lines):
            rejected += 1
            break

        possible_impedance_line = _parse_raw_csv_line(lines[index + 1])
        if _looks_like_three_winding_impedance(possible_impedance_line):
            if index + 4 >= len(lines):
                rejected += 1
                break
            winding_lines = [
                _parse_raw_csv_line(lines[index + 2]),
                _parse_raw_csv_line(lines[index + 3]),
                _parse_raw_csv_line(lines[index + 4]),
            ]
            index += 5
        else:
            winding_lines = [
                possible_impedance_line,
                _parse_raw_csv_line(lines[index + 2]),
                _parse_raw_csv_line(lines[index + 3]),
            ]
            index += 4

        if any(len(winding_line) < 6 for winding_line in winding_lines):
            rejected += 1
            continue

        rows.extend(
            _three_winding_transformer_rows(
                line_1,
                winding_lines,
                terminal_buses=(i_bus, j_bus, k_bus),
                line_id=circuit_id,
                observed_rows=observed_rows,
                raw_bus_ids=raw_bus_ids,
            )
        )

    return rows, rejected


def _raw_bus_ids(lines: list[str]) -> set[int]:
    bus_ids: set[int] = set()
    bus_started = False
    for line in lines[1:]:
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
            bus_ids.add(abs(int(float(first))))
        except ValueError:
            if bus_started:
                break
            continue
        bus_started = True
    return bus_ids


def _observed_branch_rows(
    branch_rows: Iterable[Mapping[str, object]] | None,
) -> list[dict[str, object]]:
    if not branch_rows:
        return []
    rows: list[dict[str, object]] = []
    seen: set[tuple[int | None, int | None, str]] = set()
    for row in branch_rows:
        from_bus = _integer_value(row.get("from_bus"))
        to_bus = _integer_value(row.get("to_bus"))
        line_id = _clean_raw_string(str(row.get("line_id") or ""))
        if from_bus is None or to_bus is None or not line_id:
            continue
        normalized = {"from_bus": from_bus, "to_bus": to_bus, "line_id": line_id}
        key = _branch_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        rows.append(normalized)
    return rows


def _observed_two_winding_endpoints(
    from_bus: int,
    to_bus: int,
    line_id: str,
    observed_keys: Mapping[tuple[int | None, int | None, str], Mapping[str, object]],
) -> tuple[int, int]:
    if (from_bus, to_bus, line_id) in observed_keys:
        return from_bus, to_bus
    if (to_bus, from_bus, line_id) in observed_keys:
        return to_bus, from_bus
    return from_bus, to_bus


def _looks_like_three_winding_impedance(parsed: list[str]) -> bool:
    return 9 <= len(parsed) < 14


def _three_winding_transformer_rows(
    line_1: list[str],
    winding_lines: list[list[str]],
    *,
    terminal_buses: tuple[int, int, int],
    line_id: str,
    observed_rows: list[dict[str, object]],
    raw_bus_ids: set[int],
) -> list[dict[str, object]]:
    by_internal_bus: dict[int, dict[int, dict[str, object]]] = {}
    terminal_set = set(terminal_buses)
    for row in observed_rows:
        if str(row.get("line_id") or "").strip() != line_id:
            continue
        from_bus = _integer_value(row.get("from_bus"))
        to_bus = _integer_value(row.get("to_bus"))
        if from_bus is None or to_bus is None:
            continue
        from_is_terminal = from_bus in terminal_set
        to_is_terminal = to_bus in terminal_set
        if from_is_terminal == to_is_terminal:
            continue
        terminal_bus = from_bus if from_is_terminal else to_bus
        internal_bus = to_bus if from_is_terminal else from_bus
        if internal_bus in raw_bus_ids:
            continue
        by_internal_bus.setdefault(internal_bus, {})[terminal_bus] = row

    rows: list[dict[str, object]] = []
    for internal_bus in sorted(by_internal_bus):
        terminal_rows = by_internal_bus[internal_bus]
        if not all(terminal_bus in terminal_rows for terminal_bus in terminal_buses):
            continue
        for winding_index, terminal_bus in enumerate(terminal_buses, start=1):
            observed = terminal_rows[terminal_bus]
            from_bus = _integer_value(observed.get("from_bus")) or terminal_bus
            to_bus = _integer_value(observed.get("to_bus")) or internal_bus
            rows.append(
                _transformer_metadata_row(
                    line_1,
                    winding_lines[winding_index - 1],
                    from_bus=from_bus,
                    to_bus=to_bus,
                    line_id=line_id,
                    raw_branch_type=THREE_WINDING_TRANSFORMER_BRANCH,
                    transformer_winding=str(winding_index),
                    transformer_terminal_count=3,
                    transformer_internal_bus=internal_bus,
                )
            )
    return rows


def _transformer_metadata_row(
    line_1: list[str],
    winding_line: list[str],
    *,
    from_bus: int,
    to_bus: int,
    line_id: str,
    raw_branch_type: str,
    transformer_winding: str,
    transformer_terminal_count: int,
    transformer_internal_bus: int | None = None,
    impedance_line: list[str] | None = None,
) -> dict[str, object]:
    return {
        "from_bus": from_bus,
        "to_bus": to_bus,
        "line_id": line_id,
        "r": _optional_float(impedance_line or [], 0),
        "x": _optional_float(impedance_line or [], 1),
        "b": None,
        "ratea": _optional_float(winding_line, 3),
        "rateb": _optional_float(winding_line, 4),
        "ratec": _optional_float(winding_line, 5),
        "gi": _optional_float(line_1, 7),
        "bi": _optional_float(line_1, 8),
        "gj": None,
        "bj": None,
        "status": _optional_int(line_1, 11),
        "metered_end": _optional_int(line_1, 9),
        "length": None,
        "owner_1": _optional_int(line_1, 12),
        "owner_1_fraction": _optional_float(line_1, 13),
        "raw_branch_type": raw_branch_type,
        "transformer_name": _clean_raw_string(line_1[10]) if len(line_1) > 10 else "",
        "transformer_winding": transformer_winding,
        "transformer_terminal_count": transformer_terminal_count,
        "transformer_internal_bus": transformer_internal_bus,
    }


def _append_unique_branch_row(
    rows: list[dict[str, object]],
    seen_keys: set[tuple[int | None, int | None, str]],
    row: dict[str, object],
) -> None:
    key = _branch_key(row)
    if key in seen_keys:
        return
    seen_keys.add(key)
    rows.append(row)


def _branch_key(row: Mapping[str, object]) -> tuple[int | None, int | None, str]:
    return (
        _integer_value(row.get("from_bus")),
        _integer_value(row.get("to_bus")),
        _clean_raw_string(str(row.get("line_id") or "")),
    )


def _integer_value(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


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
    "AREA_METADATA_COLUMNS",
    "BRANCH_METADATA_COLUMNS",
    "BUS_METADATA_COLUMNS",
    "parse_raw_area_metadata",
    "parse_raw_branch_metadata",
    "parse_raw_bus_metadata",
]
