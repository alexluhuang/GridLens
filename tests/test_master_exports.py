from __future__ import annotations

from pathlib import Path

from gridpack_workbench.analysis.master import MasterExportPaths, MasterExportResult, outlier_reason_for_row


def test_master_export_paths_are_grouped_by_run_exports_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "2026-06-12_12-00-00"

    paths = MasterExportPaths.for_run(run_dir)

    assert paths.exports_dir == run_dir.resolve() / "exports"
    assert paths.master_csv == paths.exports_dir / "master.csv"
    assert paths.master_cleaned_csv == paths.exports_dir / "master_cleaned.csv"
    assert paths.outliers_csv == paths.exports_dir / "outliers.csv"
    assert not paths.all_exist()


def test_master_export_result_uses_path_bundle() -> None:
    paths = MasterExportPaths.for_run("/tmp/gridpack-run")

    result = MasterExportResult.from_paths(
        paths,
        row_count=3,
        cleaned_row_count=2,
        outlier_row_count=1,
        outlier_threshold_pct=1000.0,
    )

    assert result.exports_dir == paths.exports_dir
    assert result.master_csv == paths.master_csv
    assert result.cleaned_row_count == 2
    assert result.as_dict()["master_cleaned_csv"] == str(paths.master_cleaned_csv)


def test_outlier_reason_for_row_reports_only_finite_values_above_threshold() -> None:
    row = {
        "base_case_utilization_pct": "1000",
        "mean_contingency_utilization_pct": "not-a-number",
        "max_contingency_utilization_pct": "-1200.5",
    }

    reason = outlier_reason_for_row(row, threshold_pct=1000.0)

    assert reason == "max_contingency_utilization_pct>1000"
