from __future__ import annotations

import fcntl
import os
from pathlib import Path
import threading

import pytest

from gridlens.analysis.service import AnalysisService
from gridlens.analysis.utilization import UtilizationBranchOptions


def test_shared_service_builds_in_spawned_worker(agent_project):
    updates = []
    result = AnalysisService.build(agent_project / "runs/run_a", UtilizationBranchOptions(), updates.append)
    assert result.max_line_rows
    assert max(row["max_utilization_pct"] for row in result.max_line_rows) == 120
    assert updates


def test_waiting_shared_job_can_be_cancelled(agent_project):
    cancelled = threading.Event()
    lock_path = Path("/tmp") / f"gridlens-analysis-{os.getuid()}.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        timer = threading.Timer(0.2, cancelled.set)
        timer.start()
        try:
            with pytest.raises(RuntimeError, match="cancelled"):
                AnalysisService.build(agent_project / "runs/run_a", UtilizationBranchOptions(), cancelled=cancelled)
        finally:
            timer.cancel()
