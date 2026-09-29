from __future__ import annotations

from pathlib import Path

import pytest

from gridlens.core.validation import ValidationError
from gridlens.gui.project_view_models import (
    ProjectFormValues,
    add_input_paths,
    configuration_candidates,
    default_project_folder,
    prepare_project_save,
    project_configuration_name,
    should_update_project_folder,
)


CONFIGURATION = "<Configuration><Contingency_analysis><FullBranchN1>true</FullBranchN1></Contingency_analysis><Powerflow><networkConfiguration>case.raw</networkConfiguration></Powerflow></Configuration>"
CONTINGENCY_LIST = "<Configuration><Contingency_analysis><Contingencies><Contingency><contingencyName>C1</contingencyName></Contingency></Contingencies></Contingency_analysis></Configuration>"


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


def test_prepare_project_save_allows_blank_xml_selection(tmp_path: Path) -> None:
    raw = tmp_path / "case.raw"
    raw.write_text("raw", encoding="utf-8")

    prepared = prepare_project_save(
        ProjectFormValues(
            project_name="Pilot Project",
            project_dir=tmp_path / "project",
            input_paths=[raw],
            xml_file_name=" ",
        )
    )

    assert prepared.input_files == [raw.resolve()]
    assert prepared.xml_file_name == ""


def test_prepare_project_save_requires_saved_xml_file(tmp_path: Path) -> None:
    raw = tmp_path / "case.raw"
    raw.write_text("raw", encoding="utf-8")

    with pytest.raises(ValidationError, match="saved XML file"):
        prepare_project_save(
            ProjectFormValues(
                project_name="Pilot Project",
                project_dir=tmp_path / "project",
                input_paths=[raw],
                xml_file_name="input.xml",
            )
        )


def _inputs(folder: Path, files: dict[str, str]) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return [folder / name for name in files]


def test_configuration_candidates_tell_a_configuration_from_other_xml(tmp_path: Path) -> None:
    """Only an XML with run settings is a configuration; contingency lists, other XML, and broken XML are not."""
    paths = _inputs(tmp_path, {
        "case.raw": "raw", "contingencies.xml": CONTINGENCY_LIST, "study.xml": CONFIGURATION,
        "broken.xml": "<Configuration><Powerflow>", "other.xml": "<Plot><Powerflow /></Plot>",
        "powerflow_only.xml": "<Configuration><Powerflow /></Configuration>",
    })

    assert [path.name for path in configuration_candidates(paths)] == ["study.xml", "powerflow_only.xml"]


def test_project_configuration_name_adopts_an_attached_configuration(tmp_path: Path) -> None:
    """A project without an XML uses the attached one; a chosen configuration stays while it is an input."""
    paths = _inputs(tmp_path, {"case.raw": "raw", "contingencies.xml": CONTINGENCY_LIST, "study.xml": CONFIGURATION, "input.xml": CONFIGURATION})

    assert project_configuration_name(paths, "") == "study.xml"
    assert project_configuration_name(paths, "input.xml") == "input.xml"
    assert project_configuration_name(paths, "removed.xml") == "study.xml"
    assert project_configuration_name(paths[:2], "") == ""


def test_add_input_paths_asks_before_replacing_an_input_of_the_same_name(tmp_path: Path) -> None:
    """A second file of an existing name takes its place only when the user agrees; a listed path is skipped."""
    stored = _inputs(tmp_path / "project/original_inputs", {"case.raw": "raw", "input.xml": CONFIGURATION})
    attached = _inputs(tmp_path / "attached", {"input.xml": CONFIGURATION, "monitor.csv": "1,2"})
    asked = []

    def refuse(old: Path, new: Path) -> bool:
        asked.append((old, new))
        return False

    assert add_input_paths(stored, [*attached, stored[0]], refuse) == [*stored, attached[1]]
    assert asked == [(stored[1], attached[0])]
    assert add_input_paths(stored, attached, lambda old, new: True) == [stored[0], attached[0], attached[1]]
