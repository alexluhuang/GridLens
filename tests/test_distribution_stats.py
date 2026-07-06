from __future__ import annotations

import pytest

from gridlens.analysis.distribution_stats import distribution_summary_row, percentile


def test_percentile_interpolates_between_sorted_values() -> None:
    values = [10.0, 20.0, 30.0, 40.0]

    assert percentile(values, 0.25) == 17.5
    assert percentile(values, 0.50) == 25.0
    assert percentile(values, 0.75) == 32.5


def test_percentile_rejects_out_of_range_quantiles() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        percentile([1.0], 1.5)


def test_distribution_summary_row_reports_export_table_statistics() -> None:
    row = distribution_summary_row("Area 1", [10.0, 20.0, 30.0])

    assert row == {
        "group": "Area 1",
        "count": 3,
        "mean": 20.0,
        "median": 20.0,
        "q1": 15.0,
        "q3": 25.0,
        "min": 10.0,
        "max": 30.0,
    }


def test_distribution_summary_row_skips_empty_groups() -> None:
    assert distribution_summary_row("empty", []) is None
