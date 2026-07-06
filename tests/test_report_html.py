from __future__ import annotations

from pathlib import Path

from gridlens.analysis.parser_models import OutputFile
from gridlens.analysis.report_html import DecisionSupportReportView, render_decision_support_report_html


def test_decision_support_report_html_escapes_dynamic_content() -> None:
    view = DecisionSupportReportView(
        run_path=Path("/tmp/run <unsafe>"),
        manifest_path=Path("/tmp/manifest.json"),
        table_dir=Path("/tmp/tables"),
        summary={
            "failure_count": 1,
            "thermal_facility_count": 2,
            "mean_worst_utilization_pct": 91.234,
            "gini_worst_utilization": 0.25,
            "low_voltage_violations": 0,
            "high_voltage_violations": 1,
        },
        success_note="<script>alert('note')</script>",
        success_total=3,
        success_rate_pct=66.666,
        output_files=[
            OutputFile(
                file_name="<case>.txt",
                relative_path="work/<case>.txt",
                size_bytes=42,
                suffix=".txt",
            )
        ],
        top_bottlenecks=[{"row_index": 1, "line_id": "<line>", "max_utilization_pct": 105.5}],
        voltage_low=[],
        worst_contingencies=[],
        notes=["source <raw>"],
    )

    html = render_decision_support_report_html(view)

    assert "<script>" not in html
    assert "&lt;script&gt;alert(&#x27;note&#x27;)&lt;/script&gt;" in html
    assert "/tmp/run &lt;unsafe&gt;" in html
    assert "&lt;case&gt;.txt" in html
    assert "&lt;line&gt;" in html
    assert "66.67%" in html
    assert '<p class="note">No rows available.</p>' in html
