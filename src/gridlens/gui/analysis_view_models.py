from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from gridlens.analysis.enrichment import voltage_class
from gridlens.analysis.parser_models import ParsedTable
from gridlens.analysis.utilization import (
    UtilizationBranchOptions,
    is_transformer_branch_type,
    is_utilizable_branch,
)


VOLTAGE_GROUP_ORDER = {
    "<50 kV": 0,
    "50-99 kV": 1,
    "100-229 kV": 2,
    "230-344 kV": 3,
    "345-499 kV": 4,
    "500+ kV": 5,
    "unknown": 99,
}
TRANSFORMER_STEP_ORDER = {
    "Step-up transformer": 0,
    "Step-down transformer": 1,
    "Same-voltage transformer": 2,
    "Transformer voltage unknown": 99,
}
BRANCH_KEY_COLUMNS = ("from_bus", "to_bus", "line_id", "section")
MIN_BRANCH_ANALYSIS_VOLTAGE_KV = 50.0


def summarize_control_area_utilization(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Summarize mean maximum branch utilization by actual endpoint control area."""
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if _line_voltage_kv(row) < MIN_BRANCH_ANALYSIS_VOLTAGE_KV:
            continue
        for area in _row_control_areas(row):
            buckets.setdefault(area, []).append(float(row["utilization_pct"]))

    summaries = _group_average_rows(buckets, "control_area")
    summaries.sort(key=lambda row: numeric_value(row.get("average_utilization_pct")), reverse=True)
    return summaries


def summarize_voltage_group_utilization(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Summarize mean maximum branch utilization by voltage group."""
    buckets: dict[str, list[float]] = {}
    for row in rows:
        group = _row_voltage_group(row)
        buckets.setdefault(group, []).append(float(row["utilization_pct"]))

    summaries = _group_average_rows(buckets, "voltage_group")
    summaries.sort(key=lambda row: _voltage_group_sort_key(str(row["voltage_group"])))
    return summaries


def max_line_utilization_rows(
    tables: Mapping[str, ParsedTable],
    branch_options: UtilizationBranchOptions | None = None,
) -> list[dict[str, object]]:
    """Maximum observed utilization rows for branch lines, sorted from lowest to highest."""
    duplicate_area_names = _duplicate_area_names(tables.get("area_metadata"))
    branches = _table_index(tables.get("branch_metadata"))
    rows: list[dict[str, object]] = []

    for row in _table_rows(tables, "pflow_mm"):
        key = _branch_key(row)
        branch = branches.get(key)
        if not _is_utilizable_branch(branch, branch_options):
            continue
        context = _merge_rows(branch, row)
        if _line_voltage_kv(context) < MIN_BRANCH_ANALYSIS_VOLTAGE_KV:
            continue
        utilization = _pflow_mm_max_utilization_pct(context)
        if utilization is None:
            continue
        rows.append(_line_utilization_row(context, utilization, duplicate_area_names, "pflow_mm"))

    rows.sort(key=lambda item: numeric_value(item.get("max_utilization_pct")))
    return rows


def _line_utilization_row(
    context: Mapping[str, object],
    utilization: float,
    duplicate_area_names: set[str],
    utilization_source: str,
) -> dict[str, object]:
    voltage_group = _utilization_voltage_group(context)
    return {
        "line_label": _line_label(context),
        "from_bus": context.get("from_bus", ""),
        "to_bus": context.get("to_bus", ""),
        "line_id": context.get("line_id", ""),
        "section": context.get("section", ""),
        "from_bus_name": context.get("from_bus_name", ""),
        "to_bus_name": context.get("to_bus_name", ""),
        "from_base_kv": context.get("from_base_kv", ""),
        "to_base_kv": context.get("to_base_kv", ""),
        "control_area": context.get("control_area") or context.get("area") or "unknown",
        "control_areas": _endpoint_control_area_labels(context, duplicate_area_names),
        "voltage_group": voltage_group,
        "max_contingency": _max_flow_contingency(context),
        "max_utilization_pct": round(utilization, 6),
        "utilization_pct": round(utilization, 6),
        "utilization_source": utilization_source,
        "raw_branch_type": context.get("raw_branch_type", ""),
    }


def _group_average_rows(buckets: Mapping[str, list[float]], key_column: str) -> list[dict[str, object]]:
    summaries = []
    for key, values in buckets.items():
        if not values:
            continue
        average = sum(values) / len(values)
        summaries.append(
            {
                key_column: key,
                "line_count": len(values),
                "average_utilization_pct": round(average, 6),
                "min_utilization_pct": round(min(values), 6),
                "max_utilization_pct": round(max(values), 6),
            }
        )
    return summaries


def _duplicate_area_names(table: ParsedTable | None) -> set[str]:
    if not table:
        return set()
    counts: dict[str, int] = {}
    for row in table.rows:
        name = _clean_label(row.get("area_name"))
        if name:
            counts[name] = counts.get(name, 0) + 1
    return {name for name, count in counts.items() if count > 1}


def _endpoint_control_area_labels(row: Mapping[str, object], duplicate_names: set[str]) -> list[str]:
    labels = []
    seen = set()
    for prefix in ("from", "to"):
        label = _endpoint_control_area_label(row, prefix, duplicate_names)
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    if labels:
        return labels
    fallback = _clean_label(row.get("control_area") or row.get("area"))
    return [fallback] if fallback else ["unknown"]


def _row_control_areas(row: Mapping[str, object]) -> list[str]:
    areas = row.get("control_areas")
    if isinstance(areas, str):
        return [_clean_label(areas)] if areas else []
    if isinstance(areas, Iterable):
        labels = [_clean_label(area) for area in areas]
        return [label for label in labels if label]
    fallback = _clean_label(row.get("control_area") or row.get("area"))
    return [fallback] if fallback else ["unknown"]


def _endpoint_control_area_label(
    row: Mapping[str, object],
    prefix: str,
    duplicate_names: set[str],
) -> str:
    area_id = row.get(f"{prefix}_area")
    area_name = _clean_label(row.get(f"{prefix}_area_name"))
    if area_name and area_name in duplicate_names and area_id not in (None, ""):
        return f"{area_name} ({area_id})"
    if area_name:
        return area_name
    return _clean_label(area_id)


def _clean_label(value: object) -> str:
    return " ".join(str(value or "").split())


def _table_rows(tables: Mapping[str, ParsedTable], table_name: str) -> list[dict[str, object]]:
    table = tables.get(table_name)
    return list(table.rows) if table else []


def _table_index(table: ParsedTable | None) -> dict[tuple[object, object, str, str], dict[str, object]]:
    if not table:
        return {}
    indexed: dict[tuple[object, object, str, str], dict[str, object]] = {}
    for row in table.rows:
        indexed.setdefault(_branch_key(row), row)
    return indexed


def _branch_key(row: Mapping[str, object]) -> tuple[object, object, str, str]:
    return (
        _integer_key(row.get("from_bus")),
        _integer_key(row.get("to_bus")),
        str(row.get("line_id") or "").strip(),
        str(row.get("section") or "").strip(),
    )


def _integer_key(value: object) -> object:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return value


def _merge_rows(*rows: Mapping[str, object]) -> dict[str, object]:
    merged: dict[str, object] = {}
    for row in rows:
        for key, value in row.items():
            if value not in (None, ""):
                merged[key] = value
    return merged


def _pflow_mm_max_utilization_pct(row: Mapping[str, object]) -> float | None:
    direct_utilization = _finite_float(row.get("max_utilization_pct"))
    if direct_utilization is not None:
        return direct_utilization
    rating = _line_rating(row)
    min_flow = _finite_float(row.get("min_value"))
    max_flow = _finite_float(row.get("max_value"))
    if rating is None or (min_flow is None and max_flow is None):
        return None
    return max(abs(min_flow or 0.0), abs(max_flow or 0.0)) / rating * 100


def _line_rating(row: Mapping[str, object]) -> float | None:
    return _positive_float(row.get("ratec")) or _positive_float(row.get("rate_c"))


def _is_utilizable_branch(
    row: Mapping[str, object] | None,
    branch_options: UtilizationBranchOptions | None = None,
) -> bool:
    return is_utilizable_branch(row, branch_options)


def _utilization_voltage_group(row: Mapping[str, object]) -> str:
    if is_transformer_branch_type(row.get("raw_branch_type")):
        return _transformer_step_group(row)
    computed_group = voltage_class(_line_voltage_kv(row))
    if computed_group != "unknown":
        return computed_group
    return str(row.get("voltage_class") or "unknown")


def _row_voltage_group(row: Mapping[str, object]) -> str:
    existing = str(row.get("voltage_group") or "")
    if existing and existing not in {"<100 kV", "unknown"}:
        return existing
    computed_group = _utilization_voltage_group(row)
    if computed_group != "unknown":
        return computed_group
    return existing or "unknown"


def _transformer_step_group(row: Mapping[str, object]) -> str:
    from_kv = _finite_float(row.get("from_base_kv"))
    to_kv = _finite_float(row.get("to_base_kv"))
    if from_kv is None or to_kv is None or from_kv <= 0 or to_kv <= 0:
        return "Transformer voltage unknown"
    if abs(from_kv - to_kv) <= 0.5:
        return "Same-voltage transformer"
    return "Step-up transformer" if to_kv > from_kv else "Step-down transformer"


def _voltage_group_sort_key(group: str) -> tuple[int, str]:
    if group in TRANSFORMER_STEP_ORDER:
        return (TRANSFORMER_STEP_ORDER[group], group)
    return (VOLTAGE_GROUP_ORDER.get(group, 98), group)


def _max_flow_contingency(row: Mapping[str, object]) -> object:
    direct_contingency = row.get("max_utilization_contingency")
    if direct_contingency not in (None, ""):
        return direct_contingency
    min_flow = _finite_float(row.get("min_value"))
    max_flow = _finite_float(row.get("max_value"))
    if min_flow is not None and abs(min_flow) > abs(max_flow or 0.0):
        return row.get("min_contingency", "")
    return row.get("max_contingency", "")


def _line_voltage_kv(row: Mapping[str, object]) -> float:
    values = _voltage_values(row)
    return max(values) if values else 0.0


def _voltage_values(row: Mapping[str, object]) -> list[float]:
    values = []
    for column in ("from_base_kv", "to_base_kv", "base_kv"):
        value = _finite_float(row.get(column))
        if value is not None:
            values.append(value)
    return values


def _line_label(row: Mapping[str, object]) -> str:
    from_label = str(row.get("from_bus_name") or row.get("from_bus") or "").strip()
    to_label = str(row.get("to_bus_name") or row.get("to_bus") or "").strip()
    line_id = str(row.get("line_id") or "").strip()
    if line_id:
        return f"{from_label} to {to_label} ({line_id})"
    return f"{from_label} to {to_label}"


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_float(value: object) -> float | None:
    parsed = _finite_float(value)
    return parsed if parsed is not None and parsed > 0 else None


def numeric_value(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "UtilizationBranchOptions",
    "max_line_utilization_rows",
    "numeric_value",
    "summarize_control_area_utilization",
    "summarize_voltage_group_utilization",
]
