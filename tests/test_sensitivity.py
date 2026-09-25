from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from gridlens.core import sensitivity
from gridlens.core.project import ProjectData
from gridlens.core.validation import ValidationError
from gridlens.gui.run_view_models import (
    RunFormValues,
    build_sensitivity_run_request,
)
from gridlens.psse import parse, patch


RUN_VALUES = RunFormValues(
    image="pnnl/gridpack:test",
    executable="ca.x",
    mpi_processes=1,
    pull_policy="never",
    network_disabled=True,
    use_platform_flag=True,
    use_host_user=True,
)


def edited_case(project_data: ProjectData) -> sensitivity.PatchedCase:
    """Return the base case with one generator's output changed."""
    base = sensitivity.base_case(project_data)
    case = parse.read_case(base)
    generator = case.records["generator"][0]
    edits = [patch.Edit("generator", generator.line, {"PG": "55.0"})]
    return sensitivity.PatchedCase(
        base.name, patch.apply(case, edits), patch.describe(case, edits),
        patch.summary(edits))


def test_the_base_case_is_the_network_file_the_project_xml_names(
        three_bus_project):
    project, project_data = three_bus_project

    base = sensitivity.base_case(project_data)

    assert base == project.original_inputs_dir / "three_bus_v33.raw"


def test_the_base_case_needs_an_xml_configuration(three_bus_project):
    project, project_data = three_bus_project
    project_data.xml_file_name = ""

    with pytest.raises(ValidationError, match="Configuration tab"):
        sensitivity.base_case(project_data)


def test_a_sensitivity_run_writes_the_edited_case_and_an_xml_naming_it(
        tmp_path, three_bus_project):
    project, project_data = three_bus_project
    case = edited_case(project_data)
    run_dir = tmp_path / "run"

    request = build_sensitivity_run_request(
        project_data, run_dir, RUN_VALUES, case)

    work = run_dir / "work"
    assert request.xml_filename == "input_sensitivity.xml"
    root = ET.parse(work / request.xml_filename).getroot()
    assert root.findtext("Powerflow/networkConfiguration") == case.file_name
    assert root.findtext("Contingency_analysis/contingencyRating") == "C"
    patched = parse.read_case(work / "three_bus_v33_sensitivity.raw")
    assert patched.records["generator"][0].values[2] == "55.0"
    record = json.loads((work / "sensitivity_changes.json").read_text())
    assert record["base_case"] == "three_bus_v33.raw"
    assert record["changes"][0]["fields"]["PG"] == {
        "from": "40.000", "to": "55.0"}
    assert "0 added, 1 changed, 0 removed" in request.notes


def test_a_sensitivity_run_refuses_an_input_with_a_name_it_writes(
        tmp_path, three_bus_project):
    project, project_data = three_bus_project
    clash = tmp_path / "input_sensitivity.xml"
    clash.write_text("<Configuration/>", encoding="utf-8")
    inputs = [Path(record.stored_path) for record in project_data.input_files]
    project_data = project.save([*inputs, clash], "input.xml")

    with pytest.raises(ValidationError, match="input_sensitivity.xml"):
        build_sensitivity_run_request(
            project_data, tmp_path / "run", RUN_VALUES,
            edited_case(project_data))
