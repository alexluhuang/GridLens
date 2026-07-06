from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import json
from pathlib import Path

from gridpack_workbench.analysis.csv_flat import ensure_csv_flat_parquet
from gridpack_workbench.analysis.enrichment import enrich_with_bus_metadata, voltage_class
from gridpack_workbench.analysis.metrics import compute_metrics, gini, top_share
from gridpack_workbench.analysis.parser_models import PARSER_VERSION, ParsedTable
from gridpack_workbench.analysis.parsers import parse_all_output_tables
from gridpack_workbench.analysis.table_helpers import cell_value


ANALYSIS_DATASET_VERSION = "2026.07.05"

__all__ = [
    "ANALYSIS_DATASET_VERSION",
    "RunAnalysisDataset",
    "build_run_analysis",
    "compute_metrics",
    "gini",
    "top_share",
    "voltage_class",
]


@dataclass(slots=True)
class RunAnalysisDataset:
    """Parsed run outputs, derived metrics, and generated analysis artifact paths."""

    run_dir: Path
    report_dir: Path
    table_dir: Path
    manifest_path: Path
    tables: dict[str, ParsedTable]
    metrics: dict[str, object]
    table_files: dict[str, dict[str, str]] = field(default_factory=dict)
    generated_at: str = ""

    def manifest(self) -> dict[str, object]:
        return {
            "dataset_version": ANALYSIS_DATASET_VERSION,
            "parser_version": PARSER_VERSION,
            "generated_at": self.generated_at,
            "run_dir": str(self.run_dir),
            "report_dir": str(self.report_dir),
            "table_dir": str(self.table_dir),
            "metrics": self.metrics,
            "tables": {
                name: {
                    **table.schema_dict(),
                    "csv_path": self.table_files.get(name, {}).get("csv", ""),
                    "json_path": self.table_files.get(name, {}).get("json", ""),
                    "parquet_path": self.table_files.get(name, {}).get("parquet", ""),
                }
                for name, table in self.tables.items()
            },
        }


def build_run_analysis(
    run_dir: str | Path,
    *,
    convert_csv_flat_parquet: bool = True,
    write_artifacts: bool = True,
    compute_metric_summary: bool = True,
) -> RunAnalysisDataset:
    """Parse a run directory and write reusable CSV/JSON analysis artifacts."""

    run_path = Path(run_dir).expanduser().resolve()
    report_dir = run_path / "reports"
    table_dir = report_dir / "tables"
    if write_artifacts:
        report_dir.mkdir(parents=True, exist_ok=True)
        table_dir.mkdir(parents=True, exist_ok=True)

    tables = parse_all_output_tables(run_path)
    enrich_with_bus_metadata(tables)
    metrics = compute_metrics(tables) if compute_metric_summary else {}
    parquet_files = ensure_csv_flat_parquet(run_path, tables) if convert_csv_flat_parquet else {}
    table_files = _write_tables(table_dir, tables) if write_artifacts else {}
    for name, paths in parquet_files.items():
        table_files.setdefault(name, {}).update(paths)

    dataset = RunAnalysisDataset(
        run_dir=run_path,
        report_dir=report_dir,
        table_dir=table_dir,
        manifest_path=report_dir / "analysis_manifest.json",
        tables=tables,
        metrics=metrics,
        table_files=table_files,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if write_artifacts:
        dataset.manifest_path.write_text(json.dumps(dataset.manifest(), indent=2), encoding="utf-8")
    return dataset


def _write_tables(table_dir: Path, tables: dict[str, ParsedTable]) -> dict[str, dict[str, str]]:
    written: dict[str, dict[str, str]] = {}
    for name, table in tables.items():
        csv_path = table_dir / f"{name}.csv"
        json_path = table_dir / f"{name}.json"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=table.columns, extrasaction="ignore")
            writer.writeheader()
            for row in table.rows:
                writer.writerow({column: cell_value(row.get(column)) for column in table.columns})
        json_path.write_text(json.dumps(table.rows, indent=2), encoding="utf-8")
        written[name] = {"csv": str(csv_path), "json": str(json_path)}
    return written
