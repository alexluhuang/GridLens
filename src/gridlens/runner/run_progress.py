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

The GridLens solver's GPU batch path prints no per-contingency line for the
cases it solves on the GPU. Its ``[gpu-batch pN]`` lines say how many cases go
to the GPU (``classified 9633 cases ...: 9460 GPU, 173 CPU``), how many each
finished GPU chunk holds (``GPU chunk of 8192 cases: ...``), and when every case
is reported (``paths: 9455 reported from the GPU, 173 on the CPU path, ...``).
Once the classification line appears, progress follows those lines instead of
the per-contingency markers, which then come only from the few CPU-path cases.
A run that requests the GPU path but falls back to GridPACK's CPU loop never
prints the classification, so it keeps the per-contingency counting.
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
    # Not the "1" of "N-1 contingencies".
    re.compile(r"(?<![\w-])(\d+)\s+contingencies\b", re.IGNORECASE),
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


# The GPU batch path's [gpu-batch pN] lines, from rank N of the run.
_GPU_CLASSIFIED = re.compile(r"\[gpu-batch p\d+\]\s+classified (\d+) cases in \S+ s: (\d+) GPU, (\d+) CPU")
_GPU_SWEEP = re.compile(r"\[gpu-batch p\d+\]\s+batch-size sweep: (\S+) B=(\d+)")
_GPU_BACKEND = re.compile(r"\[gpu-batch p\d+\]\s+backend (\S+) \(.*\), batch size (\d+)")
_GPU_CHUNK = re.compile(r"\[gpu-batch p\d+\]\s+GPU chunk of (\d+) cases")
_GPU_PATHS = re.compile(r"\[gpu-batch p\d+\]\s+paths: (\d+) reported from the GPU, (\d+) on the CPU path")


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
        # Set once the GPU batch path classifies the cases: how many it sends to the GPU, and how many are solved.
        self._gpu_cases: int | None = None
        self._gpu_solved = 0

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

        if "[gpu-batch p" in text:
            update = self._feed_gpu(text)
            if update is not None:
                return update

        # A per-contingency marker is the most useful signal, so check it before
        # the (structurally similar) total-count patterns.
        matched, index = self._match_completion(text) if self._gpu_cases is None else (False, None)
        if matched:
            self._completed += 1
            if index is not None:
                self._latest_index = index
            self._phase = PHASE_SOLVING
            return self._snapshot(_humanize(self._completed, self._total, self._latest_index))

        total = _match_first(text, _TOTAL_PATTERNS)
        if total is not None and total > 0 and self._phase != PHASE_POSTPROCESSING:
            # Keep the largest announced total; ignore smaller/echoed values.
            if self._total is None or total > self._total:
                self._total = total
            if self._phase == PHASE_STARTING:
                return self._snapshot(f"Preparing {self._total:,} contingencies...")
            if self._gpu_cases is None:
                return self._snapshot(_humanize(self._completed, self._total, self._latest_index))
            return None

        if self._phase == PHASE_SOLVING and _POSTPROCESS_PATTERN.search(text):
            self._phase = PHASE_POSTPROCESSING
            return self._snapshot("Writing GridPACK output files...")

        return None

    def _feed_gpu(self, text: str) -> RunProgress | None:
        """Follow the GPU batch path through its [gpu-batch pN] lines; return None for any other line.

        While the GPU solves, progress counts its cases. Reporting their results afterwards prints
        nothing per case, so the bar is then indeterminate until every case is reported.
        """
        match = _GPU_CLASSIFIED.search(text)
        if match:
            total, gpu, cpu = (int(group) for group in match.groups())
            # Markers seen before this came from the base case and setup, not from contingencies.
            self._total, self._gpu_cases, self._gpu_solved, self._completed = total, gpu, 0, 0
            self._latest_index = None
            self._phase = PHASE_SOLVING
            if not gpu:
                return self._snapshot(f"Solving powerflow on the CPU - {cpu:,} contingencies...", completed=0, total=None)
            return self._snapshot(
                f"Planning the GPU batch - {gpu:,} contingencies for the GPU, {cpu:,} for the CPU...",
                completed=0, total=None,
            )
        if self._gpu_cases is None:
            return None
        match = _GPU_SWEEP.search(text)
        if match:
            return self._snapshot(
                f"Planning the GPU batch - timing {match.group(1)} with batch size {int(match.group(2)):,}...",
                completed=0, total=None,
            )
        match = _GPU_BACKEND.search(text)
        if match:
            return self._gpu_snapshot(f" with {match.group(1)}, batch size {int(match.group(2)):,}")
        match = _GPU_CHUNK.search(text)
        if match:
            self._gpu_solved = min(self._gpu_cases, self._gpu_solved + int(match.group(1)))
            if self._gpu_solved >= self._gpu_cases:
                return self._snapshot(
                    f"Reporting results for {self._total:,} contingencies...", completed=0, total=None
                )
            return self._gpu_snapshot()
        match = _GPU_PATHS.search(text)
        if match:
            # Cases the GPU did not solve, such as diverged ones, are solved again on the CPU.
            gpu = int(match.group(1))
            self._completed = max(self._total or 0, gpu + int(match.group(2)))
            cpu = self._completed - gpu
            self._phase = PHASE_POSTPROCESSING
            return self._snapshot(
                f"Solved {self._completed:,} contingencies ({gpu:,} on the GPU, {cpu:,} on the CPU) - "
                "writing GridPACK output files...",
                total=self._completed,
            )
        return None

    def _gpu_snapshot(self, detail: str = "") -> RunProgress:
        return self._snapshot(
            f"Solving powerflow on the GPU{detail} - {self._gpu_solved:,} / {self._gpu_cases:,} contingencies",
            completed=self._gpu_solved, total=self._gpu_cases,
        )

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

    _UNSET = object()

    def _snapshot(self, message: str, *, completed: int | None = None, total: object = _UNSET) -> RunProgress:
        """Return the current state; the GPU path passes the count its bar shows, or no total for a busy bar."""
        return RunProgress(
            phase=self._phase,
            completed=self._completed if completed is None else completed,
            total=self._total if total is self._UNSET else total,
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
