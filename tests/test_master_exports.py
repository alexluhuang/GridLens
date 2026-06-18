from __future__ import annotations

import math
from pathlib import Path

import pytest

from gridpack_workbench.analysis.master import (
    BASE_FLOW_SOURCE_COLUMN,
    MAX_N1_FLOW_SOURCE_COLUMN,
    MEAN_N1_FLOW_SOURCE_COLUMN,
    MIN_N1_FLOW_SOURCE_COLUMN,
    RATE_A_COLUMN,
    MasterExportPaths,
    MasterExportResult,
    _add_utilization_columns,
    outlier_reason_for_row,
)


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


def test_add_utilization_columns_uses_named_master_source_columns() -> None:
    pd = pytest.importorskip("pandas")
    master = pd.DataFrame(
        [
            {
                RATE_A_COLUMN: 100,
                BASE_FLOW_SOURCE_COLUMN: 50,
                MEAN_N1_FLOW_SOURCE_COLUMN: -70,
                MIN_N1_FLOW_SOURCE_COLUMN: -120,
                MAX_N1_FLOW_SOURCE_COLUMN: 80,
            },
            {
                RATE_A_COLUMN: 0,
                BASE_FLOW_SOURCE_COLUMN: 50,
                MEAN_N1_FLOW_SOURCE_COLUMN: 70,
                MIN_N1_FLOW_SOURCE_COLUMN: -120,
                MAX_N1_FLOW_SOURCE_COLUMN: 80,
            },
        ]
    )

    result = _add_utilization_columns(pd, master)

    assert result.loc[0, "base_case_utilization_pct"] == 50
    assert result.loc[0, "mean_contingency_utilization_pct"] == 70
    assert result.loc[0, "max_contingency_utilization_pct"] == 120
    assert math.isnan(result.loc[1, "base_case_utilization_pct"])
