from __future__ import annotations

from contextlib import suppress
import csv
from dataclasses import dataclass
import json
from pathlib import Path

from gridlens.analysis.csv_flat import CSV_FLAT_RESULTS_TABLE
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.dataset import RunAnalysisDataset, build_run_analysis
from gridlens.analysis.parser_models import PARSER_VERSION, ParsedTable
from gridlens.analysis.table_helpers import cell_value
from gridlens.analysis.utilization import UtilizationBranchOptions
from gridlens.gui.analysis_view_models import (
    max_line_utilization_rows,
    summarize_control_area_utilization,
    summarize_voltage_group_utilization,
)


_INTERACTIVE_TABLES = ("pflow_mm", "branch_metadata", "area_metadata")
_INTERACTIVE_NOTE_ONLY_TABLES = (CSV_FLAT_RESULTS_TABLE,)
_INTERACTIVE_MANIFEST = "interactive_analysis_manifest.json"
_INTERACTIVE_TABLE_DIR = "interactive_tables"


@dataclass(slots=True)
class AnalysisBuildResult:
    dataset: RunAnalysisDataset
    max_line_rows: list[dict[str, object]]
    group_branch_rows: list[dict[str, object]]
    control_area_rows: list[dict[str, object]]
    voltage_group_rows: list[dict[str, object]]
    line_rows: list[dict[str, object]]


def build_interactive_analysis_result(
    run_dir: Path,
    branch_options: UtilizationBranchOptions,
) -> AnalysisBuildResult:
    run_path = Path(run_dir).expanduser().resolve()
    dataset = _load_cached_interactive_dataset(run_path)
    if dataset is None:
        dataset = build_run_analysis(
            run_path,
            convert_csv_flat_parquet=False,
            write_artifacts=False,
            compute_metric_summary=False,
        )
        with suppress(Exception):
            _write_cached_interactive_dataset(dataset)
    max_line_rows = max_line_utilization_rows(dataset.tables, branch_options)
    group_branch_rows = list(max_line_rows)
    control_area_rows = summarize_control_area_utilization(group_branch_rows)
    voltage_group_rows = summarize_voltage_group_utilization(group_branch_rows)
    return AnalysisBuildResult(
        dataset=dataset,
        max_line_rows=max_line_rows,
        group_branch_rows=group_branch_rows,
        control_area_rows=control_area_rows,
        voltage_group_rows=voltage_group_rows,
        line_rows=list(max_line_rows),
    )


def _load_cached_interactive_dataset(run_dir: Path) -> RunAnalysisDataset | None:
    report_dir = run_dir / "reports"
    for manifest_path in (report_dir / "analysis_manifest.json", report_dir / _INTERACTIVE_MANIFEST):
        dataset = _load_cached_manifest(run_dir, report_dir, manifest_path)
        if dataset is not None:
            return dataset
    return None


def _load_cached_manifest(run_dir: Path, report_dir: Path, manifest_path: Path) -> RunAnalysisDataset | None:
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("dataset_version") != ANALYSIS_DATASET_VERSION or manifest.get("parser_version") != PARSER_VERSION:
        return None

    table_dir = Path(str(manifest.get("table_dir") or report_dir / "tables"))
    manifest_tables = manifest.get("tables")
    if not isinstance(manifest_tables, dict):
        return None

    tables: dict[str, ParsedTable] = {}
    table_files: dict[str, dict[str, str]] = {}
    for table_name in _INTERACTIVE_TABLES:
        table_info = manifest_tables.get(table_name)
        if not isinstance(table_info, dict):
            return None
        csv_path = Path(str(table_info.get("csv_path") or table_dir / f"{table_name}.csv"))
        if not _cached_table_is_fresh(run_dir, csv_path, str(table_info.get("source_file") or "")):
            return None
        table = _read_cached_table(table_name, table_info, csv_path)
        if table is None:
            return None
        tables[table_name] = table
        table_files[table_name] = {
            "csv": str(csv_path),
            "json": str(table_info.get("json_path") or ""),
            "parquet": str(table_info.get("parquet_path") or ""),
        }

    for table_name in _INTERACTIVE_NOTE_ONLY_TABLES:
        table_info = manifest_tables.get(table_name)
        if not isinstance(table_info, dict):
            continue
        table = _read_optional_cached_table(table_name, table_info)
        if table is None:
            continue
        tables[table_name] = table
        table_files[table_name] = {
            "csv": str(table_info.get("csv_path") or ""),
            "json": str(table_info.get("json_path") or ""),
            "parquet": str(table_info.get("parquet_path") or ""),
        }

    return RunAnalysisDataset(
        run_dir=run_dir,
        report_dir=report_dir,
        table_dir=table_dir,
        manifest_path=manifest_path,
        tables=tables,
        metrics={},
        table_files=table_files,
        generated_at=str(manifest.get("generated_at") or ""),
    )


def _write_cached_interactive_dataset(dataset: RunAnalysisDataset) -> None:
    report_dir = dataset.run_dir / "reports"
    table_dir = report_dir / _INTERACTIVE_TABLE_DIR
    table_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_tables: dict[str, dict[str, object]] = {}

    for table_name in _INTERACTIVE_TABLES:
        table = dataset.tables.get(table_name)
        if not table:
            return
        csv_path = table_dir / f"{table_name}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=table.columns, extrasaction="ignore")
            writer.writeheader()
            for row in table.rows:
                writer.writerow({column: cell_value(row.get(column)) for column in table.columns})
        manifest_tables[table_name] = {
            **table.schema_dict(),
            "csv_path": str(csv_path),
            "json_path": "",
            "parquet_path": "",
        }

    for table_name in _INTERACTIVE_NOTE_ONLY_TABLES:
        table = dataset.tables.get(table_name)
        if not table:
            continue
        manifest_tables[table_name] = {
            **table.schema_dict(),
            "csv_path": "",
            "json_path": "",
            "parquet_path": "",
        }

    manifest = {
        "dataset_version": ANALYSIS_DATASET_VERSION,
        "parser_version": PARSER_VERSION,
        "generated_at": dataset.generated_at,
        "run_dir": str(dataset.run_dir),
        "report_dir": str(report_dir),
        "table_dir": str(table_dir),
        "metrics": {},
        "tables": manifest_tables,
    }
    (report_dir / _INTERACTIVE_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _read_optional_cached_table(table_name: str, table_info: dict[str, object]) -> ParsedTable | None:
    csv_path_text = str(table_info.get("csv_path") or "")
    if csv_path_text:
        table = _read_cached_table(table_name, table_info, Path(csv_path_text))
        if table is not None:
            return table
    notes = table_info.get("notes")
    columns = table_info.get("columns")
    if not isinstance(notes, list) and not isinstance(columns, list):
        return None
    return ParsedTable(
        table_name,
        str(table_info.get("source_file") or ""),
        [str(column) for column in columns] if isinstance(columns, list) else [],
        [],
        [str(note) for note in notes] if isinstance(notes, list) else [],
    )


def _cached_table_is_fresh(run_dir: Path, csv_path: Path, source_file: str) -> bool:
    if not csv_path.exists():
        return False
    if not source_file:
        return False
    source_path = run_dir / "work" / Path(source_file).name
    if not source_path.exists():
        return False
    try:
        return csv_path.stat().st_mtime >= source_path.stat().st_mtime
    except OSError:
        return False


def _read_cached_table(table_name: str, table_info: dict[str, object], csv_path: Path) -> ParsedTable | None:
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [dict(row) for row in reader]
            columns = list(reader.fieldnames or [])
    except OSError:
        return None
    if not columns:
        columns = [str(column) for column in table_info.get("columns") or []]
    notes = table_info.get("notes")
    return ParsedTable(
        table_name,
        str(table_info.get("source_file") or ""),
        columns,
        rows,
        [str(note) for note in notes] if isinstance(notes, list) else [],
    )
