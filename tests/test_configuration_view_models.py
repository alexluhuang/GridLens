from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from gridlens.core.project import Project
from gridlens.core.validation import ValidationError
from gridlens.gui.configuration_view_models import (
    InputConfigurationValues,
    default_input_configuration_values,
    load_input_configuration_values,
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
