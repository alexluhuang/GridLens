from __future__ import annotations

from dataclasses import dataclass, field
import csv
from pathlib import Path
import re
import xml.etree.ElementTree as ET


PARSER_VERSION = "2026.06.13"


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


TABLE_SCHEMAS: dict[str, dict[str, object]] = {
    "vmag": {
        "file": "vmag.txt",
        "columns": ["row_index", "bus_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": set(),
    },
    "vang": {
        "file": "vang.txt",
        "columns": ["row_index", "bus_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": set(),
    },
    "vmag_mm": {
        "file": "vmag_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": set(),
    },
    "vang_mm": {
        "file": "vang_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": set(),
    },
    "pgen": {
        "file": "pgen.txt",
        "columns": ["row_index", "bus_id", "generator_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": {"generator_id"},
    },
    "qgen": {
        "file": "qgen.txt",
        "columns": ["row_index", "bus_id", "generator_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": {"generator_id"},
    },
    "pgen_mm": {
        "file": "pgen_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "generator_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": {"generator_id"},
    },
    "qgen_mm": {
        "file": "qgen_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "generator_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": {"generator_id"},
    },
    "pflow": {
        "file": "pflow.txt",
        "columns": ["row_index", "from_bus", "to_bus", "line_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "from_bus", "to_bus"},
        "strings": {"line_id"},
    },
    "qflow": {
        "file": "qflow.txt",
        "columns": ["row_index", "from_bus", "to_bus", "line_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "from_bus", "to_bus"},
        "strings": {"line_id"},
    },
    "pflow_mm": {
        "file": "pflow_mm.txt",
        "columns": [
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_allowable",
            "max_allowable",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "from_bus", "to_bus", "min_contingency", "max_contingency"},
        "strings": {"line_id"},
    },
    "qflow_mm": {
        "file": "qflow_mm.txt",
        "columns": [
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_allowable",
            "max_allowable",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "from_bus", "to_bus", "min_contingency", "max_contingency"},
        "strings": {"line_id"},
    },
    "perf_mm": {
        "file": "perf_mm.txt",
        "columns": [
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "from_bus", "to_bus", "min_contingency", "max_contingency"},
        "strings": {"line_id"},
    },
    "perf_sum": {
        "file": "perf_sum.txt",
        "columns": ["contingency_index", "performance_index_sum", "performance_index_average"],
        "ints": {"contingency_index"},
        "strings": set(),
    },
    "line_flt_cnt": {
        "file": "line_flt_cnt.txt",
        "columns": ["row_index", "from_bus", "to_bus", "line_id", "fault_count"],
        "ints": {"row_index", "from_bus", "to_bus", "fault_count"},
        "strings": {"line_id"},
    },
    "pq_change_cnt": {
        "file": "pq_change_cnt.txt",
        "columns": ["row_index", "bus_id", "pq_change_count"],
        "ints": {"row_index", "bus_id", "pq_change_count"},
        "strings": set(),
    },
}


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


def parse_success_file(run_dir: str | Path) -> ParsedTable:
    success_file = find_success_file(run_dir)
    columns = ["contingency_index", "success", "violation", "isolated_warning", "raw_line"]
    if not success_file:
        return ParsedTable("success", "success.txt", columns, notes=["No success file was found."])

    rows: list[dict[str, object]] = []
    pattern = re.compile(
        r"contingency:\s*(?P<index>\d+)\s+success:\s*(?P<success>true|false)"
        r"(?:\s+violation:\s*(?P<violation>\w+))?"
        r"(?:\s+warning:\s*(?P<warning>\w+))?",
        flags=re.IGNORECASE,
    )
    for line in success_file.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if not match:
            continue
        warning = (match.group("warning") or "").lower()
        rows.append(
            {
                "contingency_index": int(match.group("index")),
                "success": match.group("success").lower() == "true",
                "violation": (match.group("violation") or "none").lower(),
                "isolated_warning": warning == "isolated",
                "raw_line": line.strip(),
            }
        )

    notes = []
    if not rows:
        notes.append("No schema-matching success records were found; token summary fallback is used elsewhere.")
    return ParsedTable("success", success_file.name, columns, rows, notes)


def summarize_success_file(run_dir: str | Path) -> SuccessSummary:
    success_file = find_success_file(run_dir)
    if not success_file:
        return SuccessSummary(False, "", note="No success file was found in the run work directory.")

    table = parse_success_file(run_dir)
    if table.rows:
        success_count = sum(1 for row in table.rows if row["success"] is True)
        failure_count = sum(1 for row in table.rows if row["success"] is False)
        return SuccessSummary(
            exists=True,
            file_name=success_file.name,
            success_count=success_count,
            failure_count=failure_count,
            unknown_count=0,
            total_count=len(table.rows),
            note="Counts are schema-based from success.txt contingency records.",
        )

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
        note="Counts are token-based because no exact GridPACK success schema records matched.",
    )


def parse_gridpack_table(run_dir: str | Path, table_name: str) -> ParsedTable:
    schema = TABLE_SCHEMAS[table_name]
    columns = list(schema["columns"])  # type: ignore[arg-type]
    source_file = str(schema["file"])
    path = Path(run_dir) / "work" / source_file
    if not path.exists():
        return ParsedTable(table_name, source_file, columns, notes=[f"{source_file} was not found."])

    int_columns = set(schema["ints"])  # type: ignore[arg-type]
    string_columns = set(schema["strings"])  # type: ignore[arg-type]
    rows: list[dict[str, object]] = []
    rejected = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) != len(columns):
            rejected += 1
            continue
        row: dict[str, object] = {}
        try:
            for column, value in zip(columns, parts):
                row[column] = _convert_value(value, column, int_columns, string_columns)
        except ValueError:
            rejected += 1
            continue
        rows.append(row)

    notes = []
    if rejected:
        notes.append(f"Rejected {rejected} lines that did not match the {len(columns)}-column schema.")
    return ParsedTable(table_name, source_file, columns, rows, notes)


def parse_input_xml(run_dir: str | Path) -> ParsedTable:
    path = Path(run_dir) / "work" / "input.xml"
    columns = [
        "input_file",
        "network_configuration",
        "min_voltage",
        "max_voltage",
        "qlim",
        "full_branch_n1",
        "full_generator_n1",
        "group_size",
        "output_format",
    ]
    if not path.exists():
        return ParsedTable("input_settings", "input.xml", columns, notes=["input.xml was not found."])

    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except ET.ParseError as exc:
        return ParsedTable("input_settings", "input.xml", columns, notes=[f"input.xml parse failed: {exc}"])

    row = {
        "input_file": "input.xml",
        "network_configuration": _xml_text(root, ".//networkConfiguration_v33", ""),
        "min_voltage": _xml_float(root, ".//Contingency_analysis/minVoltage"),
        "max_voltage": _xml_float(root, ".//Contingency_analysis/maxVoltage"),
        "qlim": _xml_bool(root, ".//Contingency_analysis/qlim"),
        "full_branch_n1": _xml_bool(root, ".//Contingency_analysis/FullBranchN1"),
        "full_generator_n1": _xml_bool(root, ".//Contingency_analysis/FullGeneratorN1"),
        "group_size": _xml_int(root, ".//Contingency_analysis/groupSize"),
        "output_format": _xml_text(root, ".//Contingency_analysis/outputFormat", ""),
    }
    return ParsedTable("input_settings", "input.xml", columns, [row])


def parse_raw_bus_metadata(run_dir: str | Path, raw_file_name: str = "training.raw") -> ParsedTable:
    path = Path(run_dir) / "work" / raw_file_name
    columns = ["bus_id", "bus_name", "base_kv", "area", "zone", "owner", "vm", "va"]
    if not path.exists():
        return ParsedTable("bus_metadata", raw_file_name, columns, notes=[f"{raw_file_name} was not found."])

    rows: list[dict[str, object]] = []
    bus_started = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = next(csv.reader([line], skipinitialspace=True))
        except csv.Error:
            continue
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
            bus_id = int(first)
            row = {
                "bus_id": bus_id,
                "bus_name": parsed[1].strip().strip("'").strip(),
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
    return ParsedTable("bus_metadata", raw_file_name, columns, rows, notes)


def parse_raw_branch_metadata(run_dir: str | Path, raw_file_name: str = "training.raw") -> ParsedTable:
    path = Path(run_dir) / "work" / raw_file_name
    columns = [
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
    if not path.exists():
        return ParsedTable("branch_metadata", raw_file_name, columns, notes=[f"{raw_file_name} was not found."])

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
            from_bus = abs(int(float(parsed[0])))
            to_bus = abs(int(float(parsed[1])))
            rows.append(
                {
                    "from_bus": from_bus,
                    "to_bus": to_bus,
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
        notes.append(f"Rejected {rejected} RAW branch lines that did not match the expected nontransformer branch schema.")
    if not rows:
        notes.append("No nontransformer branch records were parsed from the RAW file.")
    return ParsedTable("branch_metadata", raw_file_name, columns, rows, notes)


def parse_all_output_tables(run_dir: str | Path) -> dict[str, ParsedTable]:
    tables = {"success": parse_success_file(run_dir)}
    for table_name in TABLE_SCHEMAS:
        tables[table_name] = parse_gridpack_table(run_dir, table_name)

    input_settings = parse_input_xml(run_dir)
    tables["input_settings"] = input_settings
    raw_file = "training.raw"
    if input_settings.rows:
        candidate = str(input_settings.rows[0].get("network_configuration") or "").strip()
        if candidate:
            raw_file = Path(candidate).name
    tables["bus_metadata"] = parse_raw_bus_metadata(run_dir, raw_file)
    tables["branch_metadata"] = parse_raw_branch_metadata(run_dir, raw_file)
    return tables


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


def _convert_value(value: str, column: str, int_columns: set[str], string_columns: set[str]) -> object:
    if column in string_columns:
        return value.strip().strip("'").strip('"')
    if column in int_columns:
        return int(float(value))
    return float(value)


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


def _xml_text(root: ET.Element, path: str, default: str) -> str:
    node = root.find(path)
    if node is None or node.text is None:
        return default
    return node.text.strip()


def _xml_float(root: ET.Element, path: str) -> float | None:
    text = _xml_text(root, path, "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _xml_int(root: ET.Element, path: str) -> int | None:
    text = _xml_text(root, path, "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _xml_bool(root: ET.Element, path: str) -> bool | None:
    text = _xml_text(root, path, "").lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None
