"""Phase-level progress reporting for the analysis (graph generation) pipeline.

Building the interactive analysis parses run outputs, enriches them with RAW
metadata, and computes utilization tables. For large runs this takes several
seconds, so the pipeline reports which phase it is in via an optional
:data:`ProgressCallback`. The GUI runs the build in a separate process, so
:class:`AnalysisProgress` is a plain, picklable dataclass that can be shipped
back over a queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# Stable phase keys, ordered by when they occur in the build.
PHASE_PARSE = "parse"
PHASE_ENRICH = "enrich"
PHASE_METRICS = "metrics"
PHASE_ARTIFACTS = "artifacts"
PHASE_CHARTS = "charts"
PHASE_CACHE = "cache"
PHASE_DONE = "done"


@dataclass(slots=True)
class AnalysisProgress:
    """A phase update emitted while building the interactive analysis."""

    phase: str
    detail: str = ""
    fraction: float | None = None


ProgressCallback = Callable[[AnalysisProgress], None]


def report(callback: ProgressCallback | None, phase: str, detail: str = "", fraction: float | None = None) -> None:
    """Send a progress update if a callback was provided; otherwise do nothing."""
    if callback is None:
        return
    callback(AnalysisProgress(phase=phase, detail=detail, fraction=fraction))
