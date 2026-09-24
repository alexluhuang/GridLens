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
    assert [row["file_name"] for row in project["input_files"]] == ["case.raw"]
    assert (project["rows"], project["run_count"]) == ([], 0)
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


@pytest.fixture
def confirming(workspace):
    """Return tools that hold destructive changes for the user's confirmation, as the MCP server's do, and a project with an XML."""
    tools, inputs, projects = workspace
    tools.create_project("Study One", [str(inputs / "case.raw"), str(inputs / "monitor.txt")])
    tools.configure_run({}, project="Study One")
    return ToolService(tools.context, confirm_changes=True), inputs, projects


def test_changing_an_existing_xml_waits_for_a_confirmation_in_a_later_turn(confirming):
    """The first call previews; confirm=True counts only after the user has sent another message."""
    tools, inputs, projects = confirming
    xml = projects / "Study_One/original_inputs/input.xml"
    before = xml.read_text()
    preview = tools.configure_run({"contingency_rating": "A"}, project="Study One")["data"]
    assert preview["confirmation_required"] and xml.read_text() == before
    assert [(row["setting"], row["new"]) for row in preview["rows"]] == [("contingency_rating", "A")]
    assert "+    <contingencyRating>A</contingencyRating>" in preview["xml_diff"]
    same_turn = tools.configure_run({"contingency_rating": "A"}, project="Study One", confirm=True)
    assert same_turn["error"]["code"] == "CONFIRMATION_REQUIRED" and xml.read_text() == before
    tools.context.message("user", "Yes, switch to rating A.")
    applied = tools.configure_run({"contingency_rating": "A"}, project="Study One", confirm=True)
    assert applied["error"] is None and "<contingencyRating>A</contingencyRating>" in xml.read_text()
    # A confirmation is used once, and a change the user has not seen is previewed even with confirm=True.
    unseen = tools.configure_run({"contingency_rating": "B"}, project="Study One", confirm=True)["data"]
    assert unseen["confirmation_required"] and "ignored" in unseen["next_step"]
    # A preview goes stale when the XML changes before the user agrees, and is shown again.
    tools.configure_run({"max_voltage": "1.05"}, project="Study One")
    xml.write_text(xml.read_text() + "<!-- edited in another program -->\n")
    tools.context.message("user", "Yes.")
    assert tools.configure_run({"max_voltage": "1.05"}, project="Study One", confirm=True)["data"]["confirmation_required"]
    # A project with no XML yet gets one at once: nothing is replaced.
    tools.create_project("Study Two", [str(inputs / "case.raw")])
    created = tools.configure_run({"contingency_rating": "A"}, project="Study Two")["data"]
    assert "confirmation_required" not in created and (projects / "Study_Two/original_inputs/input.xml").is_file()


def test_replacing_an_input_waits_but_adding_one_does_not(confirming, tmp_path):
    tools, inputs, projects = confirming
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "contingencies.txt").write_text("line 1 2\n")
    added = tools.add_project_inputs([str(extra / "contingencies.txt")], project="Study One")["data"]
    assert "confirmation_required" not in added and "contingencies.txt" in {row["file_name"] for row in added["rows"]}
    (extra / "case.raw").write_text("updated case\n")
    preview = tools.add_project_inputs([str(extra / "case.raw")], project="Study One")["data"]
    assert preview["confirmation_required"] and preview["rows"][0]["action"] == "replace"
    stored = projects / "Study_One/original_inputs/case.raw"
    assert stored.read_text() != "updated case\n"
    tools.context.message("user", "Replace it.")
    assert tools.add_project_inputs([str(extra / "case.raw")], project="Study One", confirm=True)["error"] is None
    assert stored.read_text() == "updated case\n"


def test_stopping_a_running_job_waits_for_confirmation(agent_context, monkeypatch):
    tools = ToolService(agent_context, confirm_changes=True)
    running = {"job_id": "20260924T000000Z_0123abcd", "kind": "gridpack_run", "run_id": "run_a", "state": "running", "message": "contingency 40 of 90"}
    cancelled = []
    monkeypatch.setattr(gridlens_tools.jobs, "list_jobs", lambda root: [dict(running)])
    monkeypatch.setattr(gridlens_tools.jobs, "cancel_job", lambda root, job_id: cancelled.append(job_id) or {**running, "state": "cancelled"})
    preview = tools.stop(job_id=running["job_id"])["data"]
    assert preview["confirmation_required"] and preview["rows"][0]["state"] == "running" and not cancelled
    assert tools.stop(job_id=running["job_id"], confirm=True)["error"]["code"] == "CONFIRMATION_REQUIRED" and not cancelled
    assert tools.stop(run_id="run_a")["data"]["confirmation_required"]
    agent_context.message("user", "Stop it.")
    assert tools.stop(job_id=running["job_id"], confirm=True)["data"]["rows"][0]["state"] == "cancelled"
    assert cancelled == [running["job_id"]]


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


def test_status_of_runs_and_jobs_and_stop(agent_context, monkeypatch):
    """get_status reports a run, a job it can wait for, or every job; stop ends a job or a run."""
    tools = ToolService(agent_context)
    (agent_context.run("run_a") / "work/terminal.log").write_text("Total contingencies to analyze: 3\ncontingency: 1 success: true\n")
    status = tools.get_status(run_id="run_a")["data"]
    assert (status["target"], status["status"], status["progress"]["total"], status["progress"]["completed"]) == ("run", "completed", 3, 1)
    assert status["rows"][-1] == {"line": "contingency: 1 success: true"}
    started = tools.run_analysis("run_a", kind="transformer")["data"]
    assert "get_status" in started["next_step"]
    finished = tools.get_status(job_id=started["job_id"], wait_seconds=120)["data"]["rows"][0]
    assert finished["state"] == "completed", finished["output_tail"]
    assert list(finished["result"]["summaries"]) == ["transformer"]
    assert tools.get_status(run_id="run_a")["data"]["job"]["state"] == "completed"
    listed = tools.get_status()["data"]
    assert (listed["target"], [row["job_id"] for row in listed["rows"]]) == ("jobs", [started["job_id"]])
    assert tools.get_status(run_id="run_a", job_id=started["job_id"])["error"]["code"] == "ONE_TARGET"
    assert tools.get_status(job_id="not-a-job")["error"]["code"] == "INVALID_JOB_ID"
    assert tools.run_analysis("run_a", kind="lines")["error"]["code"] == "INVALID_KIND"
    stopped = []
    monkeypatch.setattr(gridlens_tools, "terminate_gridpack_run", lambda name: stopped.append(name) or GridpackTerminationResult(name, True, False, f"stopped {name}"))
    assert tools.stop(run_id="run_a")["data"]["message"] == "stopped gridlens-run_a"
    assert stopped == ["gridlens-run_a"]
    assert tools.stop(job_id=started["job_id"])["data"]["rows"][0]["state"] == "completed"
    assert tools.stop()["error"]["code"] == "ONE_TARGET"
