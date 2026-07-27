from __future__ import annotations

import json

from gridlens.core.project import Project
from gridlens.webapi.service import list_projects, load_run, read_run_status


def test_list_projects_returns_saved_project_metadata(tmp_path) -> None:
    xml = tmp_path / "input.xml"
    xml.write_text("<Configuration />", encoding="utf-8")
    network = tmp_path / "network.raw"
    network.write_text("0 / END", encoding="utf-8")

    project = Project("Pilot Study", tmp_path / "api-projects" / "Pilot_Study")
    project_data = project.save([xml, network], "input.xml")

    projects = list_projects(tmp_path / "api-projects")

    assert projects == [
        {
            "project_id": "Pilot_Study",
            "name": project_data.name,
            "root_dir": str(project.root_dir),
            "xml_file_name": "input.xml",
            "input_files": ["input.xml", "network.raw"],
            "run_count": 0,
            "created_at": project_data.created_at,
            "updated_at": project_data.updated_at,
            "latest_run_id": "",
        }
    ]


def test_read_run_status_handles_missing_invalid_and_valid_files(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    assert read_run_status(run_dir)["status"] == "not started"

    (run_dir / "status.json").write_text("{invalid", encoding="utf-8")
    assert read_run_status(run_dir)["status"] == "unknown"

    (run_dir / "status.json").write_text(json.dumps({"status": "completed", "return_code": 0}), encoding="utf-8")
    status = read_run_status(run_dir)
    assert status["status"] == "completed"
    assert status["return_code"] == 0


def test_load_run_returns_project_and_run_reference(tmp_path) -> None:
    xml = tmp_path / "input.xml"
    xml.write_text("<Configuration />", encoding="utf-8")

    project = Project("Pilot Study", tmp_path / "api-projects" / "Pilot_Study")
    project.save([xml], "input.xml")
    run_dir = project.create_run_folder()

    reference = load_run(tmp_path / "api-projects", "Pilot_Study", run_dir.name)

    assert reference.project_id == "Pilot_Study"
    assert reference.run_id == run_dir.name
    assert reference.run_dir == run_dir
