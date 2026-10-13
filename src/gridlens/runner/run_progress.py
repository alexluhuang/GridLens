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
from pathlib import Path
import re
import threading


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
        self._gpu_detail = ""
        # Contingencies the GPU batch path has reported, measured from its part files.
        self._reported = 0

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

    def feed_reported_cases(self, reported: int) -> RunProgress | None:
        """Take how many contingencies the GPU batch path has reported so far, as FlatPartMeter measures it.

        The batch path prints nothing per case, but it writes each reported case's rows to its part files,
        so their growth moves the bar smoothly. Returns an update when the count rose, else None.
        """
        if self._gpu_cases is None or self._phase != PHASE_SOLVING or reported <= self._reported:
            return None
        self._reported = min(reported, self._total or reported)
        return self._gpu_snapshot()

    def _feed_gpu(self, text: str) -> RunProgress | None:
        """Follow the GPU batch path through its [gpu-batch pN] lines; return None for any other line.

        The bar counts the contingencies reported, from feed_reported_cases, out of all of them; the GPU
        chunk lines say in the message how many of its cases the GPU has solved. A case that did not
        converge writes no rows, so the bar ends short of full until the closing paths line.
        """
        match = _GPU_CLASSIFIED.search(text)
        if match:
            total, gpu, cpu = (int(group) for group in match.groups())
            # Markers seen before this came from the base case and setup, not from contingencies.
            self._total, self._gpu_cases, self._gpu_solved, self._completed = total, gpu, 0, 0
            self._latest_index = None
            self._phase = PHASE_SOLVING
            if not gpu:
                return self._gpu_snapshot()
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
            self._gpu_detail = f" with {match.group(1)}, batch size {int(match.group(2)):,}"
            return self._gpu_snapshot()
        match = _GPU_CHUNK.search(text)
        if match:
            self._gpu_solved = min(self._gpu_cases, self._gpu_solved + int(match.group(1)))
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

    def _gpu_snapshot(self) -> RunProgress:
        """Show the contingencies reported out of all of them, and how far the GPU's own cases have got."""
        total = self._total or 0
        if self._gpu_cases and self._gpu_solved < self._gpu_cases:
            stage = f"Solving powerflow on the GPU{self._gpu_detail} - {self._gpu_solved:,} / {self._gpu_cases:,} GPU cases solved"
        elif self._gpu_cases:
            stage = f"Solved all {self._gpu_cases:,} GPU cases - reporting results"
        else:
            stage = "Solving powerflow on the CPU"
        # Until a case is reported the GPU is solving without a word, so the bar is busy rather than at 0%.
        return self._snapshot(
            f"{stage}; {self._reported:,} / {total:,} contingencies reported",
            completed=self._reported, total=(total or None) if self._reported else None,
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


class FlatPartMeter:
    """Estimate how many contingencies a running csv_flat study has reported, from its part files.

    During the case loop each MPI rank appends the rows of every case it reports to
    <outputFile>_flat.<rank>.part in the work folder; rank 0 writes the base case first. One case's rows
    are one row per monitored branch, so the base case gives the rows per case, and the rows after it
    the bytes per row. The part files are merged into the final table, and removed, after the loop.
    """

    SAMPLE_BYTES = 32 * 1024 * 1024

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self._case_bytes: float | None = None

    def reported_cases(self) -> int | None:
        """Return the contingencies reported so far, without the base case, or None before it can tell."""
        parts = list(self.work_dir.glob("*_flat.*.part"))
        if not parts:
            return None
        try:
            written = sum(part.stat().st_size for part in parts)
        except OSError:
            return None
        case_bytes = self._case_bytes or self._learn_case_bytes(parts)
        if not case_bytes:
            return None
        return max(0, round(written / case_bytes) - 1)

    def _learn_case_bytes(self, parts: list[Path]) -> float | None:
        """Measure one case's bytes from the start of rank 0's part, once a contingency's rows follow the base case."""
        first = next((part for part in parts if part.name.endswith("_flat.0.part")), None)
        if first is None:
            return None
        try:
            with first.open("rb") as handle:
                sample = handle.read(self.SAMPLE_BYTES)
        except OSError:
            return None
        lines = sample.split(b"\n")[:-1]  # the last may be cut off mid-row
        base = 0
        while base < len(lines) and lines[base].split(b",", 1)[0].strip() == b"0":
            base += 1
        after = lines[base:]
        if not base or len(after) < min(base, 1000):
            return None
        self._case_bytes = base * (sum(len(line) + 1 for line in after) / len(after))
        return self._case_bytes


def watch_flat_parts(work_dir: Path, parser: GridpackProgressParser, emit, stop, lock, interval: float = 0.5) -> threading.Thread:
    """Start a thread that feeds the parser the reported-case count every interval until stop is set.

    emit receives each update. lock is held around the parser and emit, since the output reader feeds
    the parser and emits too.
    """
    meter = FlatPartMeter(work_dir)

    def loop() -> None:
        while not stop.wait(interval):
            reported = meter.reported_cases()
            if reported is None:
                continue
            with lock:
                update = parser.feed_reported_cases(reported)
                if update is not None:
                    emit(update)

    thread = threading.Thread(target=loop, name="gridlens-flat-progress", daemon=True)
    thread.start()
    return thread

