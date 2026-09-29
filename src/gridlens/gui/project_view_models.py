from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from gridlens.core.project import Project, is_gridpack_configuration_file, safe_folder_name
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


def configuration_candidates(paths: Sequence[str | Path]) -> list[Path]:
    """Return the input files that are GridPACK run configurations, in list order."""
    return [Path(path) for path in paths if is_gridpack_configuration_file(path)]


def project_configuration_name(paths: Sequence[str | Path], current: str) -> str:
    """Return the file name of the project's GridPACK configuration among paths.

    The current configuration is kept while it is still an input. Otherwise the first attached
    configuration is used, so a project whose XML was attached rather than generated can run.
    """
    names = {Path(path).name for path in paths}
    if current and current in names:
        return current
    candidates = configuration_candidates(paths)
    return candidates[0].name if candidates else ""


def add_input_paths(
    current: Sequence[Path],
    added: Sequence[Path],
    replace: Callable[[Path, Path], bool],
) -> list[Path]:
    """Return current with added appended, asking replace(old, new) when a name is already listed.

    A project stores each input under its file name, so two inputs cannot share one. When replace
    returns True the new file takes the old one's place in the list; otherwise the new file is skipped.
    A path already listed is skipped without asking.
    """
    paths = list(current)
    for path in added:
        if path in paths:
            continue
        same_name = next((index for index, item in enumerate(paths) if item.name == path.name), None)
        if same_name is None:
            paths.append(path)
        elif replace(paths[same_name], path):
            paths[same_name] = path
    return paths


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
    "add_input_paths",
    "configuration_candidates",
    "default_project_folder",
    "prepare_project_save",
    "project_configuration_name",
    "should_update_project_folder",
]
