from __future__ import annotations

from pathlib import Path

import pytest

from gridlens.core.validation import ValidationError
from gridlens.gui.project_view_models import (
    ProjectFormValues,
    default_project_folder,
    prepare_project_save,
    should_update_project_folder,
)


def test_default_project_folder_uses_safe_project_name(tmp_path: Path) -> None:
    folder = default_project_folder(tmp_path, "Pilot Project 7")

    assert folder == tmp_path / "Pilot_Project_7"


def test_should_update_project_folder_only_updates_generated_names() -> None:
    assert should_update_project_folder("/tmp/GridPACK_Pilot_Project")
    assert should_update_project_folder("/tmp/GridPACK_Custom")
    assert not should_update_project_folder("/tmp/custom-folder")


def test_prepare_project_save_validates_and_normalizes_inputs(tmp_path: Path) -> None:
    raw = tmp_path / "case.raw"
    xml = tmp_path / "input.xml"
    raw.write_text("raw", encoding="utf-8")
    xml.write_text("<Configuration />", encoding="utf-8")

    prepared = prepare_project_save(
        ProjectFormValues(
            project_name="Pilot Project",
            project_dir=tmp_path / "project",
            input_paths=[raw, xml],
            xml_file_name=" input.xml ",
        )
    )

    assert prepared.project.name == "Pilot Project"
    assert prepared.project.root_dir == tmp_path / "project"
    assert prepared.input_files == [raw.resolve(), xml.resolve()]
    assert prepared.xml_file_name == "input.xml"


def test_prepare_project_save_requires_selected_xml_file(tmp_path: Path) -> None:
    raw = tmp_path / "case.raw"
    raw.write_text("raw", encoding="utf-8")

    with pytest.raises(ValidationError, match="selected XML file"):
        prepare_project_save(
            ProjectFormValues(
                project_name="Pilot Project",
                project_dir=tmp_path / "project",
                input_paths=[raw],
                xml_file_name="input.xml",
            )
        )
