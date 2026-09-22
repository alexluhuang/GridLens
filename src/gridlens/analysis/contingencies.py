from __future__ import annotations

import json

from gridlens.analysis.parser_models import ParsedTable


SUMMARY_NAME = "contingency_summary"
SUMMARY_COLUMNS = ["event_idx", "contingency", "monitored_facility_count", "violation_count", "max_loading_pct", "worst_facility_key", "converged", "status_code"]


def update_summary(groups: dict, row: dict) -> None:
    event = row.get("event_idx")
    key = (event, str(row.get("contingency") or ""))
    facility = json.dumps([str(row.get(name) or "") for name in ("from_bus", "to_bus", "line_id", "section")])
    loading = abs(float(row["loading_percent"]))
    group = groups.setdefault(key, dict(zip(SUMMARY_COLUMNS, [event, key[1], 0, 0, -1.0, "", None, "unknown"])))
    group["monitored_facility_count"] += 1
    group["violation_count"] += int(float(row.get("viol") or 0) != 0 or float(row["loading_percent"]) >= 100)
    if loading > group["max_loading_pct"] or loading == group["max_loading_pct"] and facility < group["worst_facility_key"]:
        group["max_loading_pct"], group["worst_facility_key"] = loading, facility


def summary_frames(data):
    """Create reductions alongside the existing branch reductions on CPU or GPU frames."""
    keys = ["event_idx", "contingency"]
    summary = data.groupby(keys).agg({"loading_percent": "count", "overloaded": "sum", "abs_loading": "max"}).reset_index()
    maxima = summary[keys + ["abs_loading"]]
    candidates = data.merge(maxima, on=keys + ["abs_loading"], how="inner")
    encoded = []
    for name in ("from_bus", "to_bus", "line_id", "section"):
        text = candidates[name].astype("str").str.replace("\\", "\\\\", regex=False).str.replace('"', '\\"', regex=False)
        encoded.append('"' + text + '"')
    candidates["worst_facility_key"] = "[" + encoded[0] + ", " + encoded[1] + ", " + encoded[2] + ", " + encoded[3] + "]"
    worst = candidates.groupby(keys)["worst_facility_key"].min().reset_index()
    return summary, worst


def summary_from_records(summary: list[dict], worst: list[dict]) -> list[dict]:
    lookup = {(row["event_idx"], row["contingency"]): row["worst_facility_key"] for row in worst}
    return [dict(zip(SUMMARY_COLUMNS, [int(row["event_idx"]), row["contingency"], int(row["loading_percent"]), int(row["overloaded"]), float(row["abs_loading"]), lookup[(row["event_idx"], row["contingency"])], None, "unknown"])) for row in summary]


def summary_table(source: str, rows: list[dict]) -> ParsedTable:
    rows.sort(key=lambda row: (float(row["event_idx"] or 0), row["contingency"]))
    return ParsedTable(SUMMARY_NAME, source, SUMMARY_COLUMNS, rows, ["Counts are recorded monitored-facility rows; includes the base case. Violations use loading >=100% or the reported flag."])


def attach_convergence(summary: ParsedTable, convergence: ParsedTable) -> None:
    lookup = {row["event_idx"]: row for row in convergence.rows}
    for row in summary.rows:
        record = lookup.get(row["event_idx"], {})
        row["status_code"] = record.get("status_code", "unknown")
        row["converged"] = record.get("converged") if row["status_code"] in ("", "OK") else False if record else None
