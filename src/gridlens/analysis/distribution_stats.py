from __future__ import annotations

from collections.abc import Iterable, Sequence
import math


GROUP_STATISTICS = ("mean", "median", "min", "max", "std", "var", "iqr", "count")
STATISTIC_DEFINITIONS = {
    "mean": "arithmetic mean of the group's object values",
    "median": "50th percentile, interpolated linearly as the box plots are",
    "min": "smallest object value in the group",
    "max": "largest object value in the group",
    "std": "population standard deviation, dividing by the object count",
    "var": "population variance, dividing by the object count, in squared units",
    "iqr": "75th minus 25th percentile, interpolated linearly",
    "count": "number of objects in the group with a known value",
}


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


def group_statistic(values: Sequence[float], statistic: str) -> float:
    """Return one of GROUP_STATISTICS for a nonempty group of values.

    std and var divide by n rather than n - 1: a group holds every object in scope, so it is a whole
    population, not a sample drawn from one.
    """
    if not values:
        raise ValueError("A group statistic needs at least one value.")
    if statistic == "count":
        return len(values)
    if statistic == "min":
        return min(values)
    if statistic == "max":
        return max(values)
    if statistic == "median":
        return percentile(values, 0.50)
    if statistic == "iqr":
        return percentile(values, 0.75) - percentile(values, 0.25)
    mean = sum(values) / len(values)
    if statistic == "mean":
        return mean
    if statistic in ("std", "var"):
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return math.sqrt(variance) if statistic == "std" else variance
    raise ValueError(f"Unknown group statistic: {statistic}")


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


__all__ = ["GROUP_STATISTICS", "STATISTIC_DEFINITIONS", "distribution_summary_row", "group_statistic", "percentile"]
