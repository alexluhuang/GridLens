from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from gridlens.core.project import Project
from gridlens.core.validation import ValidationError
from gridlens.gui.configuration_view_models import (
    InputConfigurationValues,
    default_input_configuration_values,
    attached_configuration,
    load_input_configuration_values,
    merge_input_configuration_xml,
    render_input_configuration_xml,
    save_input_configuration,
)


def test_render_input_configuration_uses_defaults_and_monitors_everything() -> None:
    xml_text = render_input_configuration_xml(
        default_input_configuration_values("case.raw", project_name="Pilot Project")
    )
    root = ET.fromstring(xml_text)
    powerflow = root.find("Powerflow")

    assert "<FullBranchN1>true</FullBranchN1>" in xml_text
    assert "<FullGeneratorN1>false</FullGeneratorN1>" in xml_text
    assert "<contingencyRating>C</contingencyRating>" in xml_text
    assert "<outputFormat>csv_flat</outputFormat>" in xml_text
    assert "<outputFile>Pilot_Project</outputFile>" in xml_text
    assert "<networkConfiguration>case.raw</networkConfiguration>" in xml_text
    assert powerflow is not None
    assert powerflow.find("outputFormat") is None
    assert powerflow.find("outputFile") is None
    assert "monitorBranchesFile" not in xml_text
    assert "monitorAreas" not in xml_text
    assert "monitorKvMin" not in xml_text
    assert "monitorKvMax" not in xml_text


def test_render_input_configuration_supports_ca_scalability_filters() -> None:
    xml_text = render_input_configuration_xml(
        InputConfigurationValues(
            network_file_name="case.raw",
            full_generator_n1=True,
            contingency_output_format="csv_delta",
            monitor_branches_file="monitor_branches.csv",
            monitor_areas="1 2",
            monitor_kv_min="100.0",
            monitor_kv_max="500.0",
            petsc_prefix="pre_",
        )
    )

    assert "<FullGeneratorN1>true</FullGeneratorN1>" in xml_text
    assert "<outputFormat>csv_delta</outputFormat>" in xml_text
    assert "<monitorBranchesFile>monitor_branches.csv</monitorBranchesFile>" in xml_text
    assert "<monitorAreas>1 2</monitorAreas>" in xml_text
    assert "<monitorKvMin>100.0</monitorKvMin>" in xml_text
    assert "<monitorKvMax>500.0</monitorKvMax>" in xml_text
    assert "<PETScPrefix>pre_</PETScPrefix>" in xml_text


def test_load_input_configuration_reads_filter_fields(tmp_path: Path) -> None:
    path = tmp_path / "input.xml"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<Configuration>
  <Contingency_analysis>
    <FullBranchN1>true</FullBranchN1>
    <FullGeneratorN1>true</FullGeneratorN1>
    <qlim>true</qlim>
    <outputFormat>csv_delta</outputFormat>
    <monitorBranchesFile>monitor.csv</monitorBranchesFile>
    <monitorAreas>1 2</monitorAreas>
    <monitorKvMin>100.0</monitorKvMin>
    <monitorKvMax>500.0</monitorKvMax>
    <contingencyRating>B</contingencyRating>
  </Contingency_analysis>
  <Powerflow>
    <networkConfiguration_v33>case.raw</networkConfiguration_v33>
    <LinearSolver>
      <PETScPrefix>pre_</PETScPrefix>
      <PETScOptions>-ksp_type richardson</PETScOptions>
    </LinearSolver>
  </Powerflow>
</Configuration>
""",
        encoding="utf-8",
    )

    values = load_input_configuration_values(path)

    assert values.full_generator_n1 is True
    assert values.contingency_output_format == "csv_delta"
    assert values.monitor_branches_file == "monitor.csv"
    assert values.monitor_areas == "1 2"
    assert values.monitor_kv_min == "100.0"
    assert values.monitor_kv_max == "500.0"
    assert values.contingency_rating == "B"
    assert values.network_configuration_tag == "networkConfiguration_v33"
    assert values.network_file_name == "case.raw"
    assert values.petsc_prefix == "pre_"


def test_input_configuration_rejects_invalid_monitor_areas() -> None:
    with pytest.raises(ValidationError, match="Monitor areas"):
        render_input_configuration_xml(
            InputConfigurationValues(
                network_file_name="case.raw",
                monitor_areas="1 north",
            )
        )


def test_save_input_configuration_requires_monitor_file_project_input(tmp_path: Path) -> None:
    raw = tmp_path / "case.raw"
    raw.write_text("raw", encoding="utf-8")
    project = Project("Monitor Project", tmp_path / "project")
    project_data = project.save([raw], "")

    with pytest.raises(ValidationError, match="Monitor branches file"):
        save_input_configuration(
            project,
            project_data,
            InputConfigurationValues(
                network_file_name="case.raw",
                monitor_branches_file="monitor.csv",
            ),
        )


ATTACHED = """<?xml version="1.0" encoding="utf-8"?>
<Configuration>
  <!-- written by hand -->
  <Contingency_analysis>
    <contingencyList>contingencies.xml</contingencyList>
    <maxVoltage units="pu">1.2</maxVoltage>
    <customSetting>kept</customSetting>
  </Contingency_analysis>
  <Powerflow>
    <networkConfiguration_v33>old.raw</networkConfiguration_v33>
    <LinearSolver>
      <SolverTag>klu</SolverTag>
    </LinearSolver>
  </Powerflow>
  <Dynamic_simulation><timeStep>0.01</timeStep></Dynamic_simulation>
</Configuration>
"""


def test_merge_updates_managed_settings_and_keeps_everything_else() -> None:
    """Saving into an attached XML changes the form's settings and keeps elements, attributes, and comments it has no field for."""
    values = replace(default_input_configuration_values("case.raw"), max_voltage="1.05", contingency_list="")
    merged = merge_input_configuration_xml(ATTACHED, values)
    root = ET.fromstring(merged)
    contingency = root.find("Contingency_analysis")
    powerflow = root.find("Powerflow")

    assert "<!-- written by hand -->" in merged
    assert contingency.find("maxVoltage").text == "1.05" and contingency.find("maxVoltage").get("units") == "pu"
    assert contingency.findtext("customSetting") == "kept"
    assert contingency.find("contingencyList") is None
    assert powerflow.find("networkConfiguration_v33") is None and powerflow.findtext("networkConfiguration") == "case.raw"
    assert powerflow.findtext("LinearSolver/SolverTag") == "klu"
    assert "-pc_type lu" in powerflow.findtext("LinearSolver/PETScOptions")
    assert root.findtext("Dynamic_simulation/timeStep") == "0.01"
    # Managed elements keep their place, and new ones go where the form writes them.
    tags = [child.tag for child in contingency]
    assert tags.index("maxVoltage") < tags.index("customSetting")
    assert tags.index("FullBranchN1") < tags.index("maxVoltage") < tags.index("minVoltage")


def test_merge_into_a_generated_xml_writes_what_render_writes() -> None:
    """A file GridLens generated merges to the same text a fresh render gives, so an unchanged save shows no diff."""
    before = default_input_configuration_values("case.raw", project_name="Pilot")
    after = replace(before, contingency_list="contingencies.xml", monitor_areas="1 2", petsc_prefix="ca")

    assert merge_input_configuration_xml(render_input_configuration_xml(before), after) == render_input_configuration_xml(after)
    assert merge_input_configuration_xml(render_input_configuration_xml(after), before) == render_input_configuration_xml(before)


def test_merge_refuses_an_xml_that_is_not_a_configuration() -> None:
    values = default_input_configuration_values("case.raw")
    with pytest.raises(ValidationError, match="not a GridPACK configuration"):
        merge_input_configuration_xml("<Configuration><Contingency_analysis><Contingencies /></Contingency_analysis></Configuration>", values)
    with pytest.raises(ValidationError, match="could not be read"):
        merge_input_configuration_xml("<Configuration>", values)


def test_saving_over_an_attached_configuration_keeps_it_and_its_origin(tmp_path: Path) -> None:
    """The Configuration tab edits an attached XML in place, and the project still records it as attached."""
    raw = tmp_path / "case.raw"
    raw.write_text("raw", encoding="utf-8")
    xml = tmp_path / "input.xml"
    xml.write_text(ATTACHED, encoding="utf-8")
    project = Project("Attached", tmp_path / "project")
    data = project.save([raw, xml], "input.xml")
    assert attached_configuration(data)
    values = load_input_configuration_values(project.original_inputs_dir / "input.xml", "case.raw", "input.xml", "Attached")

    saved = save_input_configuration(project, data, replace(values, network_file_name="case.raw", full_generator_n1=True))

    text = (project.original_inputs_dir / "input.xml").read_text(encoding="utf-8")
    assert "<customSetting>kept</customSetting>" in text and "<FullGeneratorN1>true</FullGeneratorN1>" in text
    assert attached_configuration(saved)
    resaved = project.save([Path(record.stored_path) for record in saved.input_files], saved.xml_file_name)
    assert attached_configuration(resaved)


def test_generated_configuration_is_not_attached(tmp_path: Path) -> None:
    raw = tmp_path / "case.raw"
    raw.write_text("raw", encoding="utf-8")
    project = Project("Generated", tmp_path / "project")
    data = project.save([raw], "")
    saved = save_input_configuration(project, data, default_input_configuration_values("case.raw"))
    assert saved.xml_file_name == "input.xml" and not attached_configuration(saved)
