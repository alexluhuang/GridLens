from __future__ import annotations

from collections.abc import Iterable


def distribution_summary_row(group: str, values: Iterable[float]) -> dict[str, object] | None:
    values_list = [float(value) for value in values]
    if not values_list:
        return None
    return {
        "group": group,
        "count": len(values_list),
        "mean": round(sum(values_list) / len(values_list), 8),
        "median": round(percentile(values_list, 0.50), 8),
        "q1": round(percentile(values_list, 0.25), 8),
        "q3": round(percentile(values_list, 0.75), 8),
        "min": round(min(values_list), 8),
        "max": round(max(values_list), 8),
    }


def percentile(values: Iterable[float], q: float) -> float:
    if q < 0 or q > 1:
        raise ValueError("Percentile q must be between 0 and 1.")

    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


__all__ = ["distribution_summary_row", "percentile"]
