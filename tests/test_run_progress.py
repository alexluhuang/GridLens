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


def test_parser_counts_controller_iteration_marker() -> None:
    # ca-scalability builds print no contingency index; each contingency's
    # Q-limit controller loop starts with "Controller iteration = 1".
    parser = GridpackProgressParser()
    parser.feed("Total contingencies to analyze: 8891")
    first = parser.feed(" Controller iteration = 1 ")
    second = parser.feed(" Controller iteration = 1 ")
    assert first.phase == PHASE_SOLVING
    assert first.completed == 1
    assert first.latest_index is None
    assert second.completed == 2
    assert "8,891" in second.message
    # Later controller iterations of the same contingency are NOT counted.
    assert parser.feed(" Controller iteration = 2 ") is None


def test_parser_locks_first_marker_family_and_avoids_double_counting() -> None:
    # Once "controller" locks, power-flow-converged lines must not also count.
    parser = GridpackProgressParser()
    parser.feed(" Controller iteration = 1 ")
    assert parser.completed == 1
    assert parser.feed("Power flow converged in 4 iterations") is None
    parser.feed(" Controller iteration = 1 ")
    assert parser.completed == 2


def test_parser_falls_back_to_power_flow_solves() -> None:
    parser = GridpackProgressParser()
    first = parser.feed("Power flow converged in 5 iterations")
    second = parser.feed("Power flow did NOT converge after 50 iterations")
    assert first.completed == 1
    assert second.completed == 2


def test_parser_ignores_contingency_generation_lines() -> None:
    # Setup lines mention "contingencies" (plural) and must not start counting.
    parser = GridpackProgressParser()
    assert parser.feed("Auto-generated 8160 N-1 branch contingencies") is None
    assert parser.feed("Auto-generated 731 N-1 generator contingencies") is None
    assert parser.completed == 0


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


GPU_RUN = [
    "[gpu-batch p0] GPU batch contingency path requested; effective settings:",
    " Controller iteration = 1 ",  # the base case, on each rank
    " Controller iteration = 1 ",
    "Auto-generating N-1 contingencies from network",
    "Total contingencies to analyze: 9633",
    "[gpu-batch p0] classified 9633 cases in 0.0263151 s: 9460 GPU, 173 CPU (9631 by the fast path)",
    "[gpu-batch p0] batch-size sweep: alg2 B=2048: 187.579 us per member (factor + solve)",
    "[gpu-batch p0] backend alg2 (batched left-looking LU, levels 502), batch size 2048, memory profile unified, setup 8.04354 s",
    " Controller iteration = 1 ",  # a CPU-path case
    "[gpu-batch p0] GPU chunk of 8192 cases: 8187 converged, 4 diverged, 1 flagged, 0 not run",
    "[gpu-batch p0] GPU chunk of 1268 cases: 1268 converged, 0 diverged, 0 flagged, 0 not run",
    "[gpu-batch p0] paths: 9455 reported from the GPU, 173 on the CPU path, 5 solved again on the CPU after the GPU",
    "[summary] wrote case_summary.json (9633 contingencies, 9255 converged)",
]


def test_parser_follows_the_gpu_batch_path() -> None:
    """GPU cases are counted by chunk; reporting them prints nothing per case, so the bar is then busy."""
    parser = GridpackProgressParser()
    updates = {line: parser.feed(line) for line in GPU_RUN}

    planning = updates[GPU_RUN[5]]
    assert (planning.completed, planning.total) == (0, None)
    assert "9,460" in planning.message and "173" in planning.message
    solving = updates[GPU_RUN[7]]
    assert (solving.completed, solving.total) == (0, 9460) and "alg2" in solving.message
    assert updates[GPU_RUN[8]] is None
    first_chunk = updates[GPU_RUN[9]]
    assert (first_chunk.completed, first_chunk.total) == (8192, 9460)
    reporting = updates[GPU_RUN[10]]
    assert reporting.total is None and "Reporting" in reporting.message
    done = updates[GPU_RUN[11]]
    assert done.phase == PHASE_POSTPROCESSING
    assert (done.completed, done.total, done.fraction) == (9633, 9633, 1.0)
    assert "9,455 on the GPU, 178 on the CPU" in done.message
    assert updates[GPU_RUN[12]] is None


def test_parser_counts_contingencies_when_the_gpu_path_falls_back_to_the_cpu_loop() -> None:
    """A run that requests the GPU path but never classifies its cases solves them one by one on the CPU."""
    parser = GridpackProgressParser()
    parser.feed("[gpu-batch p0] GPU batch contingency path requested; effective settings:")
    parser.feed("[gpu-batch p0] WARNING: network copies differ between ranks; using GridPACK's CPU loop")
    parser.feed("Total contingencies to analyze: 10")
    update = parser.feed(" Controller iteration = 1 ")

    assert (update.completed, update.total) == (1, 10)


def test_parser_does_not_read_n_minus_1_as_a_total() -> None:
    parser = GridpackProgressParser()

    assert parser.feed("Auto-generating N-1 contingencies from network") is None
    assert parser.total is None


def test_parser_keeps_the_writing_message_after_a_summary_line() -> None:
    parser = GridpackProgressParser()
    parser.feed("Total contingencies to analyze: 2")
    parser.feed("contingency: 1 success: true")
    parser.feed("Writing output files to success.txt")

    assert parser.feed("[summary] wrote case_summary.json (2 contingencies, 2 converged)") is None
