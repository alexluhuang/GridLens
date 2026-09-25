"""Prepare GridPACK runs of a project's case with sensitivity edits.

A sensitivity run is an ordinary run of the project's XML configuration,
except that its work folder also holds the edited case, a copy of the XML
that names the edited case as its network file, and a list of the edits.
GridPACK reads the copy, and the project's own input files stay as they are.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from gridlens.core.project import ProjectData
from gridlens.core.validation import ValidationError
from gridlens.psse import parse


CHANGES_FILE_NAME = "sensitivity_changes.json"


@dataclass(frozen=True)
class PatchedCase:
    """A project's base case with edits made, ready to run.

    changes describes each edit, as gridlens.psse.patch.describe does, and
    summary counts them.
    """

    base_name: str
    text: str
    changes: list[dict]
    summary: str

    @property
    def file_name(self) -> str:
        """Return the file name of the edited case, beside the base case."""
        base = Path(self.base_name)
        return f"{base.stem}_sensitivity{base.suffix}"


def base_case(project_data: ProjectData) -> Path:
    """Return the network file named by the project's XML configuration.

    Raises ValidationError when the project has no XML configuration, when
    the XML names no network file, or when that file is not a project input.
    """
    if not project_data.xml_file_name:
        raise ValidationError(
            "Generate the XML configuration first, in the Configuration tab.")
    xml = _read_xml(project_data)
    name = _network_element(xml.getroot()).text.strip()
    return _input_path(project_data, name)


def write_run_inputs(project_data: ProjectData, run_dir: Path,
                     case: PatchedCase) -> str:
    """Write an edited case and an XML that runs it into a run's work folder.

    Returns the file name of the XML. The run copies the project's inputs
    into the same folder later, so no file written here may share a name
    with one of them.
    """
    xml_name = f"{Path(project_data.xml_file_name).stem}_sensitivity.xml"
    inputs = {record.file_name for record in project_data.input_files}
    for name in (case.file_name, xml_name, CHANGES_FILE_NAME):
        if name in inputs:
            raise ValidationError(
                f"The project has an input file named {name}, which a "
                "sensitivity run writes. Rename that input first.")
    xml = _read_xml(project_data)
    _network_element(xml.getroot()).text = case.file_name
    work_dir = Path(run_dir) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    parse.write_case(work_dir / case.file_name, case.text)
    xml.write(work_dir / xml_name, encoding="utf-8", xml_declaration=True)
    record = {
        "base_case": case.base_name,
        "edited_case": case.file_name,
        "summary": case.summary,
        "changes": case.changes,
    }
    (work_dir / CHANGES_FILE_NAME).write_text(
        json.dumps(record, indent=2), encoding="utf-8")
    return xml_name


def run_note(case: PatchedCase) -> str:
    """Return the note a sensitivity run's manifest carries."""
    return (f"Sensitivity run of {case.base_name} with {case.summary}. "
            f"GridPACK read {case.file_name}; {CHANGES_FILE_NAME} lists the "
            "edits.")


def _read_xml(project_data: ProjectData) -> ET.ElementTree:
    """Read the project's XML configuration, keeping its comments.

    Raises ValidationError when the file is not well-formed XML.
    """
    path = _input_path(project_data, project_data.xml_file_name)
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    try:
        return ET.parse(path, parser)
    except ET.ParseError as exc:
        raise ValidationError(f"{path.name} is not valid XML: {exc}") from exc


def _input_path(project_data: ProjectData, name: str) -> Path:
    """Return where a project input file is stored, or raise if it is not."""
    for record in project_data.input_files:
        if record.file_name == name:
            return Path(record.stored_path)
    raise ValidationError(f"{name} is not one of the project's input files.")


def _network_element(root: ET.Element) -> ET.Element:
    """Return the element of an XML configuration that names the case.

    GridPACK accepts networkConfiguration and its versioned forms, such as
    networkConfiguration_v33.
    """
    for element in root.iter():
        text = (element.text or "").strip()
        if str(element.tag).startswith("networkConfiguration") and text:
            return element
    raise ValidationError("The XML configuration names no network file.")
