from __future__ import annotations

from collections.abc import Iterable, Sequence
import math
from typing import Literal, get_args


GroupStatistic = Literal["mean", "median", "min", "max", "std", "var", "iqr", "count", "sum"]
GROUP_STATISTICS = get_args(GroupStatistic)
STATISTIC_DEFINITIONS = {
    "mean": "arithmetic mean of the group's object values",
    "median": "50th percentile, interpolated linearly as the box plots are",
    "min": "smallest object value in the group",
    "max": "largest object value in the group",
    "std": "population standard deviation, dividing by the object count",
    "var": "population variance, dividing by the object count, in squared units",
    "iqr": "75th minus 25th percentile, interpolated linearly",
    "count": "number of objects in the group with a known value",
    "sum": "total of the group's values; meaningful only for additive quantities such as MW of load",
}
# The statistics that need every value rather than running totals.
ORDER_STATISTICS = frozenset({"median", "iqr"})


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
    if statistic == "sum":
        return sum(values)
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


class GroupAccumulator:
    """One group's running totals, so a statistic over millions of rows needs no list of them.

    Only the order statistics, median and iqr, keep the values themselves. The mean and variance are
    updated with Welford's method, and `merge` folds in the totals of another part of the same group,
    so partial aggregates from separate batches combine exactly.
    """

    __slots__ = ("statistic", "count", "total", "mean", "m2", "low", "high", "values")

    def __init__(self, statistic: str) -> None:
        if statistic not in GROUP_STATISTICS:
            raise ValueError(f"Unknown group statistic: {statistic}")
        self.statistic = statistic
        self.count, self.total, self.mean, self.m2 = 0, 0.0, 0.0, 0.0
        self.low, self.high = math.inf, -math.inf
        self.values: list[float] | None = [] if statistic in ORDER_STATISTICS else None

    def add(self, value: float) -> None:
        """Add one value to the group."""
        self.count += 1
        self.total += value
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.low, self.high = min(self.low, value), max(self.high, value)
        if self.values is not None:
            self.values.append(value)

    def merge(self, count: int, total: float, squares: float, low: float, high: float, values: Sequence[float] = ()) -> None:
        """Fold in another part of the group given as its count, sum, sum of squares, minimum, and maximum."""
        if not count:
            return
        mean = total / count
        m2 = max(squares - total * mean, 0.0)
        combined = self.count + count
        delta = mean - self.mean
        self.mean += delta * count / combined
        self.m2 += m2 + delta * delta * self.count * count / combined
        self.count, self.total = combined, self.total + total
        self.low, self.high = min(self.low, low), max(self.high, high)
        if self.values is not None:
            self.values.extend(values)

    def result(self) -> float:
        """Return the group's statistic. The group must hold at least one value."""
        if not self.count:
            raise ValueError("A group statistic needs at least one value.")
        name = self.statistic
        if name in ORDER_STATISTICS:
            return group_statistic(self.values, name)
        return {
            "count": lambda: self.count, "sum": lambda: self.total, "mean": lambda: self.total / self.count,
            "min": lambda: self.low, "max": lambda: self.high,
            "var": lambda: self.m2 / self.count, "std": lambda: math.sqrt(self.m2 / self.count),
        }[name]()


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


__all__ = [
    "GROUP_STATISTICS", "ORDER_STATISTICS", "STATISTIC_DEFINITIONS", "GroupAccumulator", "GroupStatistic",
    "distribution_summary_row", "group_statistic", "percentile",
]
