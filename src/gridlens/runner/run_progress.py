"""Live progress tracking for streamed GridPACK stdout.

GridPACK's contingency-analysis executable (``ca.x``) prints a line per
contingency as it solves. :class:`GridpackProgressParser` consumes those lines
one at a time, extracting the total contingency count and how many have
completed, so the GUI can render a determinate progress bar and a human status
line such as ``Solving powerflow - 2,431 / 10,000 contingencies``.

The parser is deliberately forgiving: GridPACK's exact wording varies across
versions and MPI ranks interleave their output, so several candidate patterns
are tried and completion is counted by occurrence rather than by trusting the
printed index to arrive in order.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


PHASE_STARTING = "starting"
PHASE_SOLVING = "solving"
PHASE_POSTPROCESSING = "postprocessing"
PHASE_DONE = "done"


@dataclass(slots=True)
class RunProgress:
    """A snapshot of GridPACK run progress derived from streamed stdout."""

    phase: str
    completed: int
    total: int | None
    message: str
    latest_index: int | None = None

    @property
    def fraction(self) -> float | None:
        """Completion ratio in ``[0, 1]`` when the total is known."""
        if self.total and self.total > 0:
            return min(1.0, self.completed / self.total)
        return None


# A line announcing the size of the sweep, e.g.
#   "Total number of contingencies: 10000"
#   "Number of tasks: 10000"
#   "Running 10000 contingencies"
_TOTAL_PATTERNS = (
    re.compile(r"(?:total|number)\b[^\d\n]*?(?:contingenc(?:y|ies)|tasks|events)[^\d\n]*?(\d+)", re.IGNORECASE),
    re.compile(r"(?:contingenc(?:y|ies)|tasks|events)[^\d\n]*?(?:total|count)[^\d\n]*?(\d+)", re.IGNORECASE),
    re.compile(r"\b(\d+)\s+contingencies\b", re.IGNORECASE),
)

# A line reporting that one contingency finished, e.g. the documented
# success.txt style "contingency: 2431 success: true violation: none",
# or "Processing contingency 2431", "Solving contingency 2431".
_CONTINGENCY_PATTERNS = (
    re.compile(r"contingency:?\s*(\d+)\s+success", re.IGNORECASE),
    re.compile(r"(?:processing|solving|running|completed|finished|starting)\s+contingency\s*#?\s*(\d+)", re.IGNORECASE),
    re.compile(r"\bcontingency\s*#?\s*(\d+)\b", re.IGNORECASE),
)

# Lines that mark the end of the solving sweep and the start of file writing.
_POSTPROCESS_PATTERN = re.compile(
    r"\b(writing|write)\b.*\b(output|results|files|success)\b|\bpost[- ]?process", re.IGNORECASE
)


def _humanize(completed: int, total: int | None, latest_index: int | None) -> str:
    if total:
        text = f"Solving powerflow - {completed:,} / {total:,} contingencies"
    else:
        text = f"Solving powerflow - {completed:,} contingencies solved"
    if latest_index is not None:
        text += f" (latest #{latest_index:,})"
    return text


class GridpackProgressParser:
    """Turn a stream of GridPACK stdout lines into :class:`RunProgress` updates.

    Feed each line to :meth:`feed`. It returns a :class:`RunProgress` when the
    line changed the tracked state, or ``None`` when the line was not a
    recognized progress marker. Only meaningful transitions produce an update,
    so callers can connect the result straight to a UI without extra debouncing.
    """

    def __init__(self) -> None:
        self._total: int | None = None
        self._completed = 0
        self._latest_index: int | None = None
        self._phase = PHASE_STARTING
        self._emitted_starting = False

    def reset(self) -> None:
        self.__init__()

    @property
    def total(self) -> int | None:
        return self._total

    @property
    def completed(self) -> int:
        return self._completed

    def feed(self, line: str) -> RunProgress | None:
        text = line.strip()
        if not text:
            return None

        # A completed contingency is the most common and most useful signal, so
        # check it before the (structurally similar) total-count patterns.
        index = _match_first(text, _CONTINGENCY_PATTERNS)
        if index is not None:
            self._completed += 1
            self._latest_index = index
            self._phase = PHASE_SOLVING
            return self._snapshot(_humanize(self._completed, self._total, self._latest_index))

        total = _match_first(text, _TOTAL_PATTERNS)
        if total is not None and total > 0:
            # Keep the largest announced total; ignore smaller/echoed values.
            if self._total is None or total > self._total:
                self._total = total
            message = f"Preparing {self._total:,} contingencies..."
            return self._snapshot(message)

        if self._phase == PHASE_SOLVING and _POSTPROCESS_PATTERN.search(text):
            self._phase = PHASE_POSTPROCESSING
            return self._snapshot("Writing GridPACK output files...")

        return None

    def _snapshot(self, message: str) -> RunProgress:
        return RunProgress(
            phase=self._phase,
            completed=self._completed,
            total=self._total,
            message=message,
            latest_index=self._latest_index,
        )


def _match_first(text: str, patterns: tuple[re.Pattern[str], ...]) -> int | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue
    return None
