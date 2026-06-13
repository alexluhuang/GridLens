from __future__ import annotations

import csv
import html
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

from gridpack_workbench.analysis.charts import create_success_svg
from gridpack_workbench.analysis.parsers import list_output_files, summarize_success_file


def write_output_inventory(run_dir: str | Path) -> Path:
    run_path = Path(run_dir)
    report_dir = run_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / "output_inventory.csv"

    files = list_output_files(run_path)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
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
    return output_path


def generate_run_report(run_dir: str | Path) -> dict:
    run_path = Path(run_dir).expanduser().resolve()
    report_dir = run_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    success = summarize_success_file(run_path)
    files = list_output_files(run_path)
    inventory_csv = write_output_inventory(run_path)
    chart_svg = create_success_svg(success, report_dir / "success_summary.svg")

    summary_json = report_dir / "analysis_summary.json"
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
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    html_report = report_dir / "report.html"
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(item.file_name)}</td>"
        f"<td>{html.escape(item.relative_path)}</td>"
        f"<td>{item.size_bytes}</td>"
        f"<td>{html.escape(item.suffix)}</td>"
        "</tr>"
        for item in files
    )
    html_report.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>GridPACK Workbench Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #c8ced8; padding: 8px 10px; text-align: left; }}
    th {{ background: #eef2f6; }}
    .metric {{ display: inline-block; margin-right: 24px; font-size: 18px; }}
    .note {{ color: #485366; }}
  </style>
</head>
<body>
  <h1>GridPACK Workbench Report</h1>
  <p><strong>Run folder:</strong> {html.escape(str(run_path))}</p>
  <section>
    <h2>Success Summary</h2>
    <p class="metric">Success: <strong>{success.success_count}</strong></p>
    <p class="metric">Failed: <strong>{success.failure_count}</strong></p>
    <p class="metric">Unknown: <strong>{success.unknown_count}</strong></p>
    <p class="note">{html.escape(success.note)}</p>
    <img src="success_summary.svg" alt="Contingency success summary chart">
  </section>
  <section>
    <h2>Output Files</h2>
    <table>
      <thead><tr><th>File</th><th>Path</th><th>Size bytes</th><th>Type</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
</body>
</html>
""",
        encoding="utf-8",
    )

    summary["summary_json"] = str(summary_json)
    summary["html_report"] = str(html_report)
    return summary


def export_run_zip(run_dir: str | Path, destination_zip: str | Path | None = None) -> Path:
    run_path = Path(run_dir).expanduser().resolve()
    if destination_zip is None:
        destination_zip = run_path.parent.parent / "exports" / f"{run_path.name}.zip"
    zip_path = Path(destination_zip).expanduser().resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(run_path.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(run_path.parent))
    return zip_path


def copy_report_bundle(run_dir: str | Path, destination_dir: str | Path) -> Path:
    source = Path(run_dir).expanduser().resolve() / "reports"
    destination = Path(destination_dir).expanduser().resolve()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination
