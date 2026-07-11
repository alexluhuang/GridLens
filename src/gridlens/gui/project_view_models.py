from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from gridlens.core.project import Project, safe_folder_name
from gridlens.core.validation import ValidationError, validate_existing_files


@dataclass(frozen=True, slots=True)
class ProjectFormValues:
    project_name: str
    project_dir: str | Path
    input_paths: Sequence[str | Path]
    xml_file_name: str


@dataclass(frozen=True, slots=True)
class PreparedProjectSave:
    project: Project
    input_files: list[Path]
    xml_file_name: str


def default_project_folder(default_projects_dir: str | Path, project_name: str) -> Path:
    return Path(default_projects_dir).expanduser() / safe_folder_name(project_name)


def should_update_project_folder(current_project_dir: str | Path) -> bool:
    current_name = Path(str(current_project_dir)).name
    return current_name.startswith("GridPACK")


def prepare_project_save(values: ProjectFormValues) -> PreparedProjectSave:
    input_files = validate_existing_files(list(values.input_paths))
    xml_file_name = values.xml_file_name.strip()
    if xml_file_name and xml_file_name not in {path.name for path in input_files}:
        raise ValidationError("The saved XML file must be one of the project input files.")

    return PreparedProjectSave(
        project=Project(values.project_name, values.project_dir),
        input_files=input_files,
        xml_file_name=xml_file_name,
    )


__all__ = [
    "PreparedProjectSave",
    "ProjectFormValues",
    "default_project_folder",
    "prepare_project_save",
    "should_update_project_folder",
]
