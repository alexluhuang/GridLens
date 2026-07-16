"""Live progress tracking for streamed GridPACK stdout.

GridPACK's contingency-analysis executable (``ca.x``) streams progress to
stdout as it works. :class:`GridpackProgressParser` consumes those lines one at
a time, extracting the total contingency count and how many have completed, so
the GUI can render a determinate progress bar and a human status line such as
``Solving powerflow - 2,431 / 10,000 contingencies``.

The parser is deliberately forgiving because GridPACK builds differ in what
they print, MPI ranks interleave their output, and the total is announced only
after some initial solving has begun:

* The total is read from a line such as ``Total contingencies to analyze: 8891``.
* Per-contingency progress is counted from whichever recognizable marker the
  build emits. Some builds print an explicitly numbered line
  (``contingency: 2431 success: true``); the ca-scalability builds print no
  contingency index at all, so we count the per-contingency Q-limit controller
  loop (``Controller iteration = 1``), falling back to completed power-flow
  solves. The first marker family seen is locked in for the rest of the run so
  a build that prints two markers per contingency is never double-counted.

Completion is counted by occurrence, not by trusting any printed index to
arrive in order, since MPI ranks report out of order.
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

# Ordered families of "one contingency" markers. GridPACK builds differ in what
# they print per contingency: some emit an explicitly numbered line, while
# others (e.g. the ca-scalability builds) print only power-flow diagnostics with
# no contingency index at all. The parser tries these families in order, then
# LOCKS onto the first family that matches and counts only that family for the
# rest of the run -- so a build that prints two recognizable markers per
# contingency is never double-counted.
_COMPLETION_FAMILIES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    # Explicitly numbered contingencies (documented success.txt style, or
    # "Solving contingency N"). These carry an index we can surface to the user.
    (
        "indexed",
        (
            re.compile(r"contingency:?\s*(\d+)\s+success", re.IGNORECASE),
            re.compile(
                r"(?:processing|solving|running|completed|finished|starting)\s+contingency\s*#?\s*(\d+)",
                re.IGNORECASE,
            ),
            re.compile(r"\bcontingency\s*#?\s*(\d+)\b", re.IGNORECASE),
        ),
    ),
    # Per-contingency outer power-flow (Q-limit) controller loop. GridPACK prints
    # "Controller iteration = 1" exactly once at the start of each contingency's
    # solve, so it maps one-to-one with contingencies.
    (
        "controller",
        (re.compile(r"\bcontroller\s+iteration\s*=\s*0*1\b", re.IGNORECASE),),
    ),
    # Fallback: each completed power-flow solve. This can exceed the contingency
    # count when contingencies re-solve (Q-limit enforcement forces a PQ
    # conversion and another solve), so it is only used when nothing better
    # appears earlier in the stream.
    (
        "solve",
        (re.compile(r"\bpower\s+flow\s+(?:converged|did\s+not\s+converge)", re.IGNORECASE),),
    ),
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
        self._locked_family: str | None = None

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

        # A per-contingency marker is the most useful signal, so check it before
        # the (structurally similar) total-count patterns.
        matched, index = self._match_completion(text)
        if matched:
            self._completed += 1
            if index is not None:
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

    def _match_completion(self, text: str) -> tuple[bool, int | None]:
        """Return ``(matched, index)`` for a per-contingency marker line.

        Once a family matches, the parser locks to it and ignores the others,
        so builds that emit more than one recognizable marker per contingency
        are counted once. ``index`` is ``None`` for markers without a number.
        """
        for name, patterns in _COMPLETION_FAMILIES:
            if self._locked_family is not None and name != self._locked_family:
                continue
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    self._locked_family = name
                    index: int | None = None
                    if match.groups():
                        try:
                            index = int(match.group(1))
                        except (ValueError, IndexError):
                            index = None
                    return True, index
        return False, None

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
