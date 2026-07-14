from __future__ import annotations

from gridlens.runner.run_progress import (
    PHASE_POSTPROCESSING,
    PHASE_SOLVING,
    GridpackProgressParser,
    RunProgress,
)


def test_parser_ignores_unrelated_lines() -> None:
    parser = GridpackProgressParser()
    assert parser.feed("Starting Docker run...") is None
    assert parser.feed("") is None
    assert parser.feed("PETSc initialized") is None


def test_parser_extracts_total_before_solving() -> None:
    parser = GridpackProgressParser()
    update = parser.feed("Total number of contingencies: 10000")
    assert isinstance(update, RunProgress)
    assert update.total == 10000
    assert update.completed == 0
    assert "10,000" in update.message


def test_parser_counts_documented_success_lines() -> None:
    parser = GridpackProgressParser()
    parser.feed("Total number of contingencies: 3")
    first = parser.feed("contingency: 1 success: true violation: none")
    second = parser.feed("contingency: 2 success: true violation: branch")
    third = parser.feed("contingency: 3 success: false")

    assert first.phase == PHASE_SOLVING
    assert first.completed == 1
    assert first.latest_index == 1
    assert first.fraction == 1 / 3
    assert third.completed == 3
    assert third.total == 3
    assert third.fraction == 1.0
    assert "3 / 3" in third.message


def test_parser_counts_by_occurrence_not_index_order() -> None:
    # MPI ranks interleave, so indices can arrive out of order. Completion is
    # counted per line rather than trusting the printed index to be monotonic.
    parser = GridpackProgressParser()
    parser.feed("Number of tasks: 100")
    parser.feed("Solving contingency 7")
    update = parser.feed("Solving contingency 3")
    assert update.completed == 2
    assert update.latest_index == 3
    assert update.total == 100


def test_parser_detects_postprocessing_phase() -> None:
    parser = GridpackProgressParser()
    parser.feed("contingency: 1 success: true")
    update = parser.feed("Writing output files to success.txt")
    assert update is not None
    assert update.phase == PHASE_POSTPROCESSING


def test_run_progress_fraction_without_total() -> None:
    progress = RunProgress(phase=PHASE_SOLVING, completed=5, total=None, message="")
    assert progress.fraction is None


def test_parser_reset_clears_state() -> None:
    parser = GridpackProgressParser()
    parser.feed("Total number of contingencies: 5")
    parser.feed("contingency: 1 success: true")
    parser.reset()
    assert parser.total is None
    assert parser.completed == 0
