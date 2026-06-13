from __future__ import annotations

from pathlib import Path

from gridpack_workbench.analysis.parsers import SuccessSummary


def create_success_svg(summary: SuccessSummary, output_svg: str | Path) -> Path:
    output_path = Path(output_svg)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    success = max(summary.success_count, 0)
    failure = max(summary.failure_count, 0)
    total = max(success + failure, 1)
    max_value = max(success, failure, 1)

    width = 720
    height = 360
    chart_left = 90
    chart_bottom = 290
    bar_width = 120
    scale_height = 210

    success_height = int(scale_height * success / max_value)
    failure_height = int(scale_height * failure / max_value)
    success_x = 190
    failure_x = 410
    success_y = chart_bottom - success_height
    failure_y = chart_bottom - failure_height

    success_pct = success / total * 100
    failure_pct = failure / total * 100

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="36" y="42" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="#172033">Contingency Success Summary</text>
  <line x1="{chart_left}" y1="{chart_bottom}" x2="650" y2="{chart_bottom}" stroke="#485366" stroke-width="2"/>
  <line x1="{chart_left}" y1="78" x2="{chart_left}" y2="{chart_bottom}" stroke="#485366" stroke-width="2"/>
  <rect x="{success_x}" y="{success_y}" width="{bar_width}" height="{success_height}" fill="#2f7d57"/>
  <rect x="{failure_x}" y="{failure_y}" width="{bar_width}" height="{failure_height}" fill="#b33a3a"/>
  <text x="{success_x + 60}" y="{success_y - 12}" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#172033">{success}</text>
  <text x="{failure_x + 60}" y="{failure_y - 12}" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#172033">{failure}</text>
  <text x="{success_x + 60}" y="325" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#172033">Success ({success_pct:.1f}%)</text>
  <text x="{failure_x + 60}" y="325" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#172033">Failed ({failure_pct:.1f}%)</text>
</svg>
"""
    output_path.write_text(svg, encoding="utf-8")
    return output_path
