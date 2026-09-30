"""Background jobs: detached workers that run GridPACK or build an analysis and record the outcome."""
from __future__ import annotations

import json
import os
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
    (folder / "job.json").write_text(json.dumps({"job_id": folder.name, "kind": kind, "project_root": str(project), "run_id": run.name, "run_dir": str(run), "request": request, "pid": pid or 1}))
    return folder


def test_detached_analysis_job_reports_branch_and_transformer_summaries(agent_project):
    """A real worker process builds from the fixture cache and records both summaries."""
    run = agent_project / "runs/run_a"
    started = jobs.start_job(agent_project, "analysis", run, {"kinds": ["branch", "transformer"], "include_index": False, "rebuild": False})
    assert started["state"] in ("queued", "running", "completed")
    finished = jobs.wait_for_job(agent_project, started["job_id"], 120)
    assert finished["state"] == "completed", finished["log_tail"]
    summaries = finished["result"]["summaries"]
    assert (summaries["branch"]["facility_count"], summaries["branch"]["highest_max_utilization_pct"]) == (3, 120.0)
    assert summaries["transformer"]["facility_count"] == 1
    assert [job["job_id"] for job in jobs.list_jobs(agent_project)] == [started["job_id"]]
    folder = agent_project / jobs.JOBS_FOLDER / started["job_id"]
    assert Path(finished["log"]) == folder / "job.log"
    # One record and one readable log; no separate status file, no empty output file, no stray cuFile log.
    assert sorted(path.name for path in folder.iterdir()) == ["job.json", "job.log"]
    record = json.loads((folder / "job.json").read_text())
    assert (record["state"], record["request"]["kinds"], record["pid"]) == ("completed", ["branch", "transformer"], finished["pid"])
    log = (folder / "job.log").read_text()
    assert "Queued analysis job" in log and "Started the analysis job" in log and "Completed: The analysis cache is ready" in log
    assert "branch: 3 facilities; highest loading 120.0%" in log


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
    status = json.loads((folder / "job.json").read_text())
    assert (status["state"], status["result"]["return_code"]) == ("completed", 0)
    assert status["progress"]["total"] == 4
    assert status["request"]["notes"] == "from the agent"
    assert "Completed: GridPACK exited with code 0. The branch and transformer analysis is ready." in (folder / "job.log").read_text()
    assert (seen[0].image, seen[0].mpi_processes, seen[0].network_mode, seen[0].notes) == ("pnnl/gridpack:test", 4, "none", "from the agent")
    # A completed run goes on to prepare both analyses, as a run from the Run tab does.
    assert (status["result"]["summaries"]["branch"]["facility_count"], status["result"]["summaries"]["transformer"]["facility_count"]) == (3, 1)
    assert "Preparing the branch and transformer analysis." in (folder / "job.log").read_text()

    import gridlens.analysis.service as service

    def broken_build(*_args, **_kwargs):
        raise RuntimeError("Traceback (most recent call last):\nValueError: run has no results")

    monkeypatch.setattr(service.AnalysisService, "build", staticmethod(broken_build))
    assert jobs.run_job(folder) == 0
    status = json.loads((folder / "job.json").read_text())
    # The run succeeded, so the job did too; the failed build is reported for run_analysis to retry.
    assert (status["state"], status["result"]["analysis_error"]) == ("completed", "ValueError: run has no results")
    assert "Preparing its analysis failed" in status["message"]

    def broken_run(request, log_callback=None):
        raise RuntimeError("docker is not running")

    monkeypatch.setattr(runner, "run_gridpack_case", broken_run)
    assert jobs.run_job(folder) == 1
    status = json.loads((folder / "job.json").read_text())
    assert (status["state"], status["message"]) == ("failed", "RuntimeError: docker is not running")
    log = (folder / "job.log").read_text()
    assert "Failed: RuntimeError: docker is not running" in log and "Traceback" in log


def test_a_sensitivity_run_job_runs_the_xml_that_names_the_edited_case(agent_project, monkeypatch):
    """start_sensitivity_run records the XML copy it wrote; the worker runs that XML instead of the project's."""
    xml = agent_project / "input.xml"
    xml.write_text("<Configuration/>")
    (agent_project / "project.json").unlink()
    Project("Synthetic Project", agent_project).save([xml], "input.xml")
    form = {"image": "pnnl/gridpack:test", "executable": "ca.x", "mpi_processes": 1, "pull_policy": "never", "network_disabled": True, "use_platform_flag": True, "use_host_user": True, "memory_limit": "", "extra_docker_args": ""}
    folder = _job(agent_project, "gridpack_run", {"form": form, "notes": "Sensitivity run", "xml_file": "input_sensitivity.xml"})
    seen = []

    def fake_run(request, log_callback=None):
        seen.append(request)
        return GridpackRunResult(1, request.run_dir, request.run_dir / "logs/run.log", request.run_dir / "work/terminal.log", request.run_dir / "status.json", request.run_dir / "manifest.json")

    import gridlens.runner.gridpack_runner as runner
    monkeypatch.setattr(runner, "run_gridpack_case", fake_run)
    jobs.run_job(folder)
    assert (seen[0].xml_filename, seen[0].notes) == ("input_sensitivity.xml", "Sensitivity run")


def test_lost_workers_are_reported_and_cancelling_stops_the_worker(agent_project, monkeypatch):
    """A worker that vanished is failed, not running forever, and cancel_job ends a live worker's group."""
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    folder = _job(agent_project, "analysis", {"kinds": ["branch"]}, pid=gone.pid)
    record = json.loads((folder / "job.json").read_text())
    (folder / "job.json").write_text(json.dumps({**record, "state": "running", "message": "Started."}))
    lost = jobs.read_job(agent_project, folder.name)
    assert lost["state"] == "failed" and "without recording a result" in lost["message"]
    monkeypatch.setattr(jobs, "gridlens_command", lambda *arguments: [sys.executable, "-c", "import time; time.sleep(60)"])
    started = jobs.start_job(agent_project, "analysis", agent_project / "runs/run_a", {"kinds": ["branch"]})
    cancelled = jobs.cancel_job(agent_project, started["job_id"])
    assert cancelled["state"] == "cancelled"
    assert jobs.cancel_job(agent_project, started["job_id"])["state"] == "cancelled"
    assert "Cancelled" in (agent_project / jobs.JOBS_FOLDER / started["job_id"] / "job.log").read_text()


def test_legacy_job_folders_are_still_read(agent_project):
    """A job written with a separate status.json and output.log is read as before."""
    folder = _job(agent_project, "analysis", {"kinds": ["branch"]})
    (folder / "status.json").write_text(json.dumps({"state": "completed", "message": "Done.", "result": {"summaries": {}}}))
    (folder / "output.log").write_text("line one\nline two\n")
    job = jobs.read_job(agent_project, folder.name)
    assert (job["state"], job["message"], job["request"]["kinds"]) == ("completed", "Done.", ["branch"])
    assert (Path(job["log"]).name, job["log_tail"]) == ("output.log", ["line one", "line two"])
    assert jobs.cancel_job(agent_project, folder.name)["state"] == "completed"


def test_worker_waits_for_its_pid_before_writing(agent_project, monkeypatch):
    """The worker never writes job.json before start_job records the pid, so neither write is lost."""
    folder = _job(agent_project, "analysis", {"kinds": ["branch"]})
    record = json.loads((folder / "job.json").read_text())
    (folder / "job.json").write_text(json.dumps({**record, "pid": None}))
    monkeypatch.setattr(jobs, "PID_WAIT_SECONDS", 0.2)
    jobs._wait_for_pid(folder)
    assert json.loads((folder / "job.json").read_text())["pid"] == os.getpid()


@pytest.mark.parametrize("job_id,code", [("../../etc", "INVALID_JOB_ID"), ("20260922T000000Z_ffffffff", "JOB_NOT_FOUND")])
def test_job_ids_are_checked(agent_project, job_id, code):
    with pytest.raises(AgentError) as error:
        jobs.read_job(agent_project, job_id)
    assert error.value.code == code
