from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

from gridpack_workbench.analysis.charts import create_success_svg
from gridpack_workbench.analysis.dataset import RunAnalysisDataset, build_run_analysis
from gridpack_workbench.analysis.master import build_branch_master_exports
from gridpack_workbench.analysis.parsers import list_output_files, summarize_success_file
from gridpack_workbench.analysis.report_html import DecisionSupportReportView, render_decision_support_report_html


@dataclass(frozen=True, slots=True)
class DecisionSupportReportPaths:
    run_dir: Path
    report_dir: Path
    inventory_csv: Path
    success_chart_svg: Path
    summary_json: Path
    html_report: Path
    legacy_html_report: Path

    @classmethod
    def for_run(cls, run_dir: str | Path) -> DecisionSupportReportPaths:
        run_path = Path(run_dir).expanduser().resolve()
        report_dir = run_path / "reports"
        return cls(
            run_dir=run_path,
            report_dir=report_dir,
            inventory_csv=report_dir / "output_inventory.csv",
            success_chart_svg=report_dir / "success_summary.svg",
            summary_json=report_dir / "analysis_summary.json",
            html_report=report_dir / "decision_support_report.html",
            legacy_html_report=report_dir / "report.html",
        )

    def ensure_report_dir(self) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def default_zip_path(self) -> Path:
        return self.run_dir.parent.parent / "exports" / f"{self.run_dir.name}.zip"


def write_output_inventory(run_dir: str | Path) -> Path:
    paths = DecisionSupportReportPaths.for_run(run_dir)
    paths.ensure_report_dir()

    files = list_output_files(paths.run_dir)
    with paths.inventory_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file_name", "relative_path", "size_bytes", "suffix"])
        writer.writeheader()
        for item in files:
            writer.writerow(
                {
                    "file_name": item.file_name,
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "suffix": item.suffix,
                }
            )
    return paths.inventory_csv


def generate_decision_support_report(run_dir: str | Path, dataset: RunAnalysisDataset | None = None) -> dict:
    run_path = Path(run_dir).expanduser().resolve()
    dataset = dataset or build_run_analysis(run_path)
    paths = DecisionSupportReportPaths.for_run(run_path)
    paths.ensure_report_dir()

    success = summarize_success_file(run_path)
    files = list_output_files(run_path)
    inventory_csv = write_output_inventory(run_path)
    chart_svg = create_success_svg(success, paths.success_chart_svg)
    master_exports = build_branch_master_exports(run_path, dataset)

    thermal = dataset.metrics.get("thermal", {})
    voltage = dataset.metrics.get("voltage", {})
    success_metrics = dataset.metrics.get("success", {})
    summary = {
        "run_dir": str(run_path),
        "success_file": success.file_name,
        "success_count": success.success_count,
        "failure_count": success.failure_count,
        "unknown_count": success.unknown_count,
        "total_count": success.total_count,
        "note": success.note,
        "output_file_count": len(files),
        "inventory_csv": str(inventory_csv),
        "chart_svg": str(chart_svg),
        "master": master_exports.as_dict(),
        "analysis_manifest": str(dataset.manifest_path),
        "table_dir": str(dataset.table_dir),
        "thermal_facility_count": thermal.get("facility_count", 0) if isinstance(thermal, dict) else 0,
        "mean_worst_utilization_pct": thermal.get("mean_worst_utilization_pct") if isinstance(thermal, dict) else None,
        "gini_worst_utilization": thermal.get("gini_worst_utilization") if isinstance(thermal, dict) else None,
        "low_voltage_violations": voltage.get("low_voltage_violations", 0) if isinstance(voltage, dict) else 0,
        "high_voltage_violations": voltage.get("high_voltage_violations", 0) if isinstance(voltage, dict) else 0,
    }
    paths.summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    top_bottlenecks = thermal.get("top_bottlenecks", []) if isinstance(thermal, dict) else []
    voltage_low = voltage.get("worst_low_voltage", []) if isinstance(voltage, dict) else []
    contingency = dataset.metrics.get("contingencies", {})
    worst_contingencies = contingency.get("worst_by_performance_index", []) if isinstance(contingency, dict) else []
    notes = dataset.metrics.get("notes", [])
    report_view = DecisionSupportReportView(
        run_path=run_path,
        manifest_path=dataset.manifest_path,
        table_dir=dataset.table_dir,
        summary=summary,
        success_note=success.note,
        success_total=success_metrics.get("total", success.total_count)
        if isinstance(success_metrics, dict)
        else success.total_count,
        success_rate_pct=success_metrics.get("success_rate_pct") if isinstance(success_metrics, dict) else None,
        output_files=files,
        top_bottlenecks=top_bottlenecks,
        voltage_low=voltage_low,
        worst_contingencies=worst_contingencies,
        notes=notes if isinstance(notes, list) else [],
    )
    paths.html_report.write_text(render_decision_support_report_html(report_view), encoding="utf-8")

    summary["summary_json"] = str(paths.summary_json)
    summary["html_report"] = str(paths.html_report)
    if paths.legacy_html_report != paths.html_report:
        paths.legacy_html_report.write_text(paths.html_report.read_text(encoding="utf-8"), encoding="utf-8")
    summary["legacy_html_report"] = str(paths.legacy_html_report)
    return summary


def generate_run_report(run_dir: str | Path) -> dict:
    """Compatibility wrapper for the original Analysis tab/report API."""
    return generate_decision_support_report(run_dir)


def export_run_zip(run_dir: str | Path, destination_zip: str | Path | None = None) -> Path:
    paths = DecisionSupportReportPaths.for_run(run_dir)
    run_path = paths.run_dir
    if destination_zip is None:
        destination_zip = paths.default_zip_path()
    zip_path = Path(destination_zip).expanduser().resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(run_path.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(run_path.parent))
    return zip_path


def copy_report_bundle(run_dir: str | Path, destination_dir: str | Path) -> Path:
    source = DecisionSupportReportPaths.for_run(run_dir).report_dir
    destination = Path(destination_dir).expanduser().resolve()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination
