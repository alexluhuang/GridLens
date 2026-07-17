from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from gridlens.analysis.csv_flat import (
    CSV_FLAT_BRANCH_TABLE,
    merge_csv_flat_branch_metadata,
    parse_csv_flat_outputs,
    parse_csv_flat_success,
)
from gridlens.analysis.parser_models import OutputFile, PARSER_VERSION, ParsedTable, SuccessSummary
from gridlens.analysis.progress import ProgressCallback
from gridlens.analysis.raw_parsers import (
    parse_raw_area_metadata,
    parse_raw_branch_metadata,
    parse_raw_bus_metadata,
)
from gridlens.analysis.table_schemas import TABLE_SCHEMAS


SUCCESS_COLUMNS = ["contingency_index", "success", "violation", "isolated_warning", "raw_line"]


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
    if not success_file:
        csv_flat_success = parse_csv_flat_success(run_dir)
        if csv_flat_success:
            return csv_flat_success
        return _empty_success_table()

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
    return ParsedTable("success", success_file.name, list(SUCCESS_COLUMNS), rows, notes)


def summarize_success_file(run_dir: str | Path) -> SuccessSummary:
    success_file = find_success_file(run_dir)
    table = parse_success_file(run_dir)
    if table.rows:
        success_count = sum(1 for row in table.rows if row["success"] is True)
        failure_count = sum(1 for row in table.rows if row["success"] is False)
        return SuccessSummary(
            exists=True,
            file_name=success_file.name if success_file else table.source_file,
            success_count=success_count,
            failure_count=failure_count,
            unknown_count=0,
            total_count=len(table.rows),
            note=f"Counts are schema-based from {table.source_file} contingency records.",
        )

    if not success_file:
        return SuccessSummary(False, "", note="No success.txt or csv_flat convergence file was found in the run work directory.")

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
    columns = list(schema["columns"])
    source_file = schema["file"]
    path = Path(run_dir) / "work" / source_file
    if not path.exists():
        return ParsedTable(table_name, source_file, columns, notes=[f"{source_file} was not found."])

    int_columns = schema["ints"]
    string_columns = schema["strings"]
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
    run_path = Path(run_dir)
    path = _find_input_xml(run_path)
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
    if not path:
        return ParsedTable("input_settings", "input.xml", columns, notes=["No input XML file was found."])

    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except ET.ParseError as exc:
        return ParsedTable("input_settings", path.name, columns, notes=[f"{path.name} parse failed: {exc}"])

    row = {
        "input_file": path.name,
        "network_configuration": _xml_first_text(
            root,
            [
                ".//networkConfiguration_v33",
                ".//networkConfiguration_v34",
                ".//networkConfiguration",
            ],
            "",
        ),
        "min_voltage": _xml_float(root, ".//Contingency_analysis/minVoltage"),
        "max_voltage": _xml_float(root, ".//Contingency_analysis/maxVoltage"),
        "qlim": _xml_bool(root, ".//Contingency_analysis/qlim"),
        "full_branch_n1": _xml_bool(root, ".//Contingency_analysis/FullBranchN1"),
        "full_generator_n1": _xml_bool(root, ".//Contingency_analysis/FullGeneratorN1"),
        "group_size": _xml_int(root, ".//Contingency_analysis/groupSize"),
        "output_format": _xml_text(root, ".//Contingency_analysis/outputFormat", ""),
    }
    return ParsedTable("input_settings", path.name, columns, [row])


def _find_input_xml(run_path: Path) -> Path | None:
    work_dir = run_path / "work"
    if not work_dir.exists():
        return None

    for file_name in _manifest_input_xml_names(run_path / "manifest.json"):
        candidate = work_dir / Path(file_name).name
        if candidate.exists():
            return candidate

    default = work_dir / "input.xml"
    if default.exists():
        return default

    xml_files = sorted(path for path in work_dir.glob("*.xml") if path.is_file())
    for path in xml_files:
        if _looks_like_gridpack_input_xml(path):
            return path
    return xml_files[0] if xml_files else None


def _manifest_input_xml_names(manifest_path: Path) -> list[str]:
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []

    names = []
    xml_file = str(manifest.get("xml_file") or "").strip()
    if xml_file:
        names.append(xml_file)
    for item in manifest.get("input_files") or []:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file_name") or "").strip()
        if file_name.lower().endswith(".xml"):
            names.append(file_name)
    return names


def _looks_like_gridpack_input_xml(path: Path) -> bool:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except (ET.ParseError, OSError):
        return False
    return bool(_xml_first_text(root, [".//networkConfiguration_v33", ".//networkConfiguration_v34", ".//networkConfiguration"], ""))


def parse_all_output_tables(run_dir: str | Path, progress: ProgressCallback | None = None) -> dict[str, ParsedTable]:
    success_file = find_success_file(run_dir)
    tables = {
        "success": parse_success_file(run_dir) if success_file else _empty_success_table()
    }
    for table_name in TABLE_SCHEMAS:
        tables[table_name] = parse_gridpack_table(run_dir, table_name)

    csv_flat_tables = parse_csv_flat_outputs(run_dir, progress=progress)
    for table_name, table in csv_flat_tables.items():
        if table_name == "success" and tables["success"].rows:
            continue
        tables[table_name] = table

    input_settings = parse_input_xml(run_dir)
    tables["input_settings"] = input_settings
    raw_file = "training.raw"
    if input_settings.rows:
        candidate = str(input_settings.rows[0].get("network_configuration") or "").strip()
        if candidate:
            raw_file = Path(candidate).name

    raw_bus_metadata = parse_raw_bus_metadata(run_dir, raw_file)
    raw_area_metadata = parse_raw_area_metadata(run_dir, raw_file)
    if raw_bus_metadata.rows:
        tables["bus_metadata"] = raw_bus_metadata
    else:
        tables.setdefault("bus_metadata", raw_bus_metadata)
    if raw_area_metadata.rows:
        tables["area_metadata"] = raw_area_metadata
    else:
        tables.setdefault("area_metadata", raw_area_metadata)

    raw_branch_metadata = parse_raw_branch_metadata(
        run_dir,
        raw_file,
        branch_rows=_observed_branch_rows(tables),
    )
    tables["branch_metadata"] = merge_csv_flat_branch_metadata(
        raw_branch_metadata,
        tables.get(CSV_FLAT_BRANCH_TABLE),
    )
    return tables


def _empty_success_table() -> ParsedTable:
    return ParsedTable("success", "success.txt", list(SUCCESS_COLUMNS), notes=["No success file was found."])


def _observed_branch_rows(tables: dict[str, ParsedTable]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for table_name in (
        "pflow",
        "pflow_mm",
        "qflow",
        "qflow_mm",
        "perf_mm",
        "line_flt_cnt",
        CSV_FLAT_BRANCH_TABLE,
    ):
        table = tables.get(table_name)
        if table:
            rows.extend(table.rows)
    return rows


def sniff_table(path: str | Path, max_rows: int = 20) -> list[list[str]]:
    table_path = Path(path)
    if not table_path.exists() or not table_path.is_file():
        return []

    text = table_path.read_text(encoding="utf-8", errors="replace")
    sample = text[:4096]
    dialect = _sniff_csv_dialect(sample)

    rows = []
    if dialect is not None:
        reader = csv.reader(text.splitlines(), dialect)
        for row in reader:
            rows.append(row)
            if len(rows) >= max_rows:
                break
        return rows

    for line in text.splitlines()[:max_rows]:
        rows.append(line.split())
    return rows


def _sniff_csv_dialect(sample: str) -> type[csv.Dialect] | csv.Dialect | None:
    try:
        return csv.Sniffer().sniff(sample)
    except csv.Error:
        if "," in sample:
            return csv.excel
        return None


def _convert_value(value: str, column: str, int_columns: set[str], string_columns: set[str]) -> object:
    if column in string_columns:
        return value.strip().strip("'").strip('"')
    if column in int_columns:
        return int(float(value))
    return float(value)


def _xml_first_text(root: ET.Element, paths: list[str], default: str) -> str:
    for path in paths:
        value = _xml_text(root, path, "")
        if value:
            return value
    return default


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


__all__ = [
    "OutputFile",
    "PARSER_VERSION",
    "ParsedTable",
    "SuccessSummary",
    "find_success_file",
    "list_output_files",
    "parse_all_output_tables",
    "parse_gridpack_table",
    "parse_input_xml",
    "parse_raw_area_metadata",
    "parse_raw_branch_metadata",
    "parse_raw_bus_metadata",
    "parse_success_file",
    "sniff_table",
    "summarize_success_file",
]
