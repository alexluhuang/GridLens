"""The GridLens operation tools set up projects, configure and start runs, and build analyses."""
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

import gridlens.agent.gridlens_tools as gridlens_tools
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import ToolService
from gridlens.core.app_settings import AppSettings
from gridlens.runner.docker_probe import ProbeResult
from gridlens.runner.gridpack_runner import GridpackTerminationResult


@pytest.fixture
def workspace(tmp_path):
    """Return tools for a session with no project open, a projects folder, and input files to import."""
    inputs = tmp_path / "downloads"
    inputs.mkdir()
    (inputs / "case.raw").write_text(" 0, 100.00, 33, 0, 0, 60.00\ntitle\ntitle\n1,'A', 230.0,3,1,1,1,1.0,0.0\n0 / END OF BUS DATA\nQ\n")
    (inputs / "monitor.txt").write_text("1 2 1\n")
    projects = tmp_path / "projects"
    context = SessionContext.create(None, (), "fixture:model", "http://127.0.0.1:11434", projects_dir=projects)
    return ToolService(context), inputs, projects


def test_create_list_and_describe_projects(workspace):
    """A created project is a normal GridLens project: listed, described, and refused a second time."""
    tools, inputs, projects = workspace
    created = tools.create_project("Study One", [str(inputs / "case.raw")])
    assert created["error"] is None
    assert Path(created["data"]["folder"]) == (projects / "Study_One").resolve()
    assert (projects / "Study_One/original_inputs/case.raw").is_file()
    listed = tools.list_projects()["data"]["rows"]
    assert [(row["name"], row["run_count"], row["open_in_gui"]) for row in listed] == [("Study One", 0, False)]
    project = tools.get_project("Study One")["data"]
    assert [row["file_name"] for row in project["rows"]] == ["case.raw"]
    assert tools.create_project("Study One", [str(inputs / "case.raw")])["error"]["code"] == "PROJECT_EXISTS"
    assert tools.create_project("Study Two", ["case.raw"])["error"]["code"] == "ABSOLUTE_PATH_REQUIRED"
    missing = tools.create_project("Study Two", [str(inputs / "missing.raw")])["error"]
    assert (missing["code"], missing["remedy"].startswith("Input file does not exist")) == ("INVALID_INPUT", True)
    assert tools.get_project()["error"]["code"] == "NO_PROJECT"


def test_configure_run_writes_the_xml_the_configuration_tab_would(workspace):
    """Settings are validated, coerced to the form's types, and saved as the project's XML."""
    tools, inputs, projects = workspace
    tools.create_project("Study One", [str(inputs / "case.raw"), str(inputs / "monitor.txt")])
    configuration = tools.get_run_configuration("Study One")["data"]
    by_name = {row["setting"]: row for row in configuration["rows"]}
    assert (by_name["network_file_name"]["value"], by_name["contingency_rating"]["choices"]) == ("case.raw", ["A", "B", "C"])
    assert configuration["network_files"] == ["case.raw"]
    saved = tools.configure_run({"full_generator_n1": "true", "max_voltage": 1.05, "contingency_rating": "B", "monitor_branches_file": "monitor.txt"}, project="Study One")
    assert saved["error"] is None
    root = ET.parse(saved["data"]["xml_file"]).getroot()
    assert [root.findtext(f"Contingency_analysis/{tag}") for tag in ("FullGeneratorN1", "maxVoltage", "contingencyRating", "monitorBranchesFile")] == ["true", "1.05", "B", "monitor.txt"]
    assert tools.get_project("Study One")["data"]["xml_file_name"] == "input.xml"
    assert {row["setting"]: row["value"] for row in tools.get_run_configuration("Study One")["data"]["rows"]}["max_voltage"] == "1.05"
    assert tools.configure_run({"no_such_setting": 1}, project="Study One")["error"]["code"] == "UNKNOWN_SETTING"
    assert tools.configure_run({"contingency_rating": "Z"}, project="Study One")["error"]["code"] == "INVALID_INPUT"
    assert tools.configure_run({"full_branch_n1": "sometimes"}, project="Study One")["error"]["code"] == "INVALID_SETTING"
    assert tools.configure_run({"network_file_name": "other.raw"}, project="Study One")["error"]["code"] == "NETWORK_FILE_NOT_IN_PROJECT"


def test_add_project_inputs_replaces_a_file_of_the_same_name(workspace, tmp_path):
    tools, inputs, projects = workspace
    tools.create_project("Study One", [str(inputs / "case.raw")])
    newer = tmp_path / "newer"
    newer.mkdir()
    (newer / "case.raw").write_text("updated case\n")
    (newer / "contingencies.txt").write_text("line 1 2\n")
    added = tools.add_project_inputs([str(newer / "case.raw"), str(newer / "contingencies.txt")], project="Study One")["data"]
    assert sorted(row["file_name"] for row in added["rows"]) == ["case.raw", "contingencies.txt"]
    assert (projects / "Study_One/original_inputs/case.raw").read_text() == "updated case\n"


def test_start_run_checks_docker_then_starts_a_job(workspace, monkeypatch):
    """start_run fills in the Run tab's saved settings, checks Docker and the image, and starts a job."""
    tools, inputs, projects = workspace
    tools.create_project("Study One", [str(inputs / "case.raw")])
    assert tools.start_run("Study One")["error"]["code"] == "NO_CONFIGURATION"
    tools.configure_run({}, project="Study One")
    monkeypatch.setattr(AppSettings, "load", classmethod(lambda cls, path=None: cls(default_gridpack_image="pnnl/gridpack:test", default_mpi_processes=8)))
    monkeypatch.setattr(gridlens_tools.docker_probe, "docker_engine_available", lambda: ProbeResult(False, "Cannot connect to the Docker daemon"))
    assert tools.start_run("Study One")["error"]["code"] == "DOCKER_UNAVAILABLE"
    monkeypatch.setattr(gridlens_tools.docker_probe, "docker_engine_available", lambda: ProbeResult(True, "Docker Engine 27"))
    monkeypatch.setattr(gridlens_tools.docker_probe, "image_exists", lambda image: ProbeResult(image == "pnnl/gridpack:test", "checked"))
    assert tools.start_run("Study One", image="missing:image")["error"]["code"] == "IMAGE_NOT_AVAILABLE"
    started = []
    monkeypatch.setattr(gridlens_tools.jobs, "start_job", lambda root, kind, run, request: started.append((root, kind, run, request)) or {"job_id": "20260922T000000Z_0123abcd", "state": "queued"})
    result = tools.start_run("Study One", mpi_processes=2, notes="agent run")
    assert result["error"] is None
    root, kind, run, request = started[0]
    assert (kind, run.parent, request["form"]["image"], request["form"]["mpi_processes"], request["form"]["network_disabled"], request["notes"]) == ("gridpack_run", root / "runs", "pnnl/gridpack:test", 2, True, "agent run")
    assert result["data"]["run_id"] == run.name and (run / "work").is_dir()


def test_run_status_analysis_job_and_stop(agent_context, monkeypatch):
    """A completed run reports its status and progress; its analysis runs as a job that get_job can wait for."""
    tools = ToolService(agent_context)
    (agent_context.run("run_a") / "work/terminal.log").write_text("Total contingencies to analyze: 3\ncontingency: 1 success: true\n")
    status = tools.get_run_status("run_a")["data"]
    assert (status["status"], status["progress"]["total"], status["progress"]["completed"]) == ("completed", 3, 1)
    assert status["rows"][-1] == {"line": "contingency: 1 success: true"}
    started = tools.run_analysis("run_a", kind="transformer")["data"]
    finished = tools.get_job(started["job_id"], wait_seconds=120)["data"]["rows"][0]
    assert finished["state"] == "completed", finished["output_tail"]
    assert list(finished["result"]["summaries"]) == ["transformer"]
    assert tools.get_run_status("run_a")["data"]["job"]["state"] == "completed"
    assert [row["job_id"] for row in tools.list_jobs()["data"]["rows"]] == [started["job_id"]]
    assert tools.run_analysis("run_a", kind="lines")["error"]["code"] == "INVALID_KIND"
    stopped = []
    monkeypatch.setattr(gridlens_tools, "terminate_gridpack_run", lambda name: stopped.append(name) or GridpackTerminationResult(name, True, False, f"stopped {name}"))
    assert tools.stop_run("run_a")["data"]["message"] == "stopped gridlens-run_a"
    assert stopped == ["gridlens-run_a"]
