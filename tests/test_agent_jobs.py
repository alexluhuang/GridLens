"""Background jobs: detached workers that run GridPACK or build an analysis and record the outcome."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

import gridlens.agent.jobs as jobs
from gridlens.agent.policy import AgentError
from gridlens.core.project import Project
from gridlens.runner.gridpack_runner import GridpackRunResult


def _job(project: Path, kind: str, request: dict, pid: int | None = None) -> Path:
    """Write a job record by hand, as start_job would, without starting a worker."""
    folder = project / jobs.JOBS_FOLDER / "20260922T000000Z_0123abcd"
    folder.mkdir(parents=True)
    run = project / "runs/run_a"
    (folder / "job.json").write_text(json.dumps({"job_id": folder.name, "kind": kind, "project_root": str(project), "run_id": run.name, "run_dir": str(run), "request": request, "pid": pid}))
    return folder


def test_detached_analysis_job_reports_branch_and_transformer_summaries(agent_project):
    """A real worker process builds from the fixture cache and records both summaries."""
    run = agent_project / "runs/run_a"
    started = jobs.start_job(agent_project, "analysis", run, {"kinds": ["branch", "transformer"], "include_index": False, "rebuild": False})
    assert started["state"] in ("queued", "running", "completed")
    finished = jobs.wait_for_job(agent_project, started["job_id"], 120)
    assert finished["state"] == "completed", finished["output_tail"]
    summaries = finished["result"]["summaries"]
    assert (summaries["branch"]["facility_count"], summaries["branch"]["highest_max_utilization_pct"]) == (3, 120.0)
    assert summaries["transformer"]["facility_count"] == 1
    assert [job["job_id"] for job in jobs.list_jobs(agent_project)] == [started["job_id"]]
    assert Path(finished["output_log"]).parent == agent_project / jobs.JOBS_FOLDER / started["job_id"]


def test_gridpack_job_records_progress_and_outcome(agent_project, monkeypatch):
    """The worker builds the same run request as the Run tab and records GridPACK's progress and exit code."""
    xml = agent_project / "input.xml"
    xml.write_text("<Configuration/>")
    (agent_project / "project.json").unlink()  # The fixture's minimal record lacks what Project.save reads back.
    Project("Synthetic Project", agent_project).save([xml], "input.xml")
    form = {"image": "pnnl/gridpack:test", "executable": "ca.x", "mpi_processes": 4, "pull_policy": "never", "network_disabled": True, "use_platform_flag": True, "use_host_user": True, "memory_limit": "", "extra_docker_args": ""}
    folder = _job(agent_project, "gridpack_run", {"form": form, "notes": "from the agent"})
    seen = []

    def fake_run(request, log_callback=None):
        seen.append(request)
        log_callback("Total contingencies to analyze: 4\n")
        return GridpackRunResult(0, request.run_dir, request.run_dir / "logs/run.log", request.run_dir / "work/terminal.log", request.run_dir / "status.json", request.run_dir / "manifest.json")

    import gridlens.runner.gridpack_runner as runner
    monkeypatch.setattr(runner, "run_gridpack_case", fake_run)
    assert jobs.run_job(folder) == 0
    status = json.loads((folder / "status.json").read_text())
    assert (status["state"], status["result"]["return_code"]) == ("completed", 0)
    assert status["progress"]["total"] == 4
    assert (seen[0].image, seen[0].mpi_processes, seen[0].network_mode, seen[0].notes) == ("pnnl/gridpack:test", 4, "none", "from the agent")

    def broken_run(request, log_callback=None):
        raise RuntimeError("docker is not running")

    monkeypatch.setattr(runner, "run_gridpack_case", broken_run)
    assert jobs.run_job(folder) == 1
    status = json.loads((folder / "status.json").read_text())
    assert (status["state"], status["message"]) == ("failed", "RuntimeError: docker is not running")


def test_lost_workers_are_reported_and_cancelling_stops_the_worker(agent_project, monkeypatch):
    """A worker that vanished is failed, not running forever, and cancel_job ends a live worker's group."""
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    folder = _job(agent_project, "analysis", {"kinds": ["branch"]}, pid=gone.pid)
    (folder / "status.json").write_text(json.dumps({"state": "running", "message": "Started."}))
    lost = jobs.read_job(agent_project, folder.name)
    assert lost["state"] == "failed" and "without recording a result" in lost["message"]
    monkeypatch.setattr(jobs, "gridlens_command", lambda *arguments: [sys.executable, "-c", "import time; time.sleep(60)"])
    started = jobs.start_job(agent_project, "analysis", agent_project / "runs/run_a", {"kinds": ["branch"]})
    cancelled = jobs.cancel_job(agent_project, started["job_id"])
    assert cancelled["state"] == "cancelled"
    assert jobs.cancel_job(agent_project, started["job_id"])["state"] == "cancelled"


@pytest.mark.parametrize("job_id,code", [("../../etc", "INVALID_JOB_ID"), ("20260922T000000Z_ffffffff", "JOB_NOT_FOUND")])
def test_job_ids_are_checked(agent_project, job_id, code):
    with pytest.raises(AgentError) as error:
        jobs.read_job(agent_project, job_id)
    assert error.value.code == code
