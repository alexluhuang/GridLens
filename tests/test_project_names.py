"""Project folders are ones every platform can create and tell apart."""
from __future__ import annotations

from pathlib import Path

import pytest

from gridlens.core import project
from gridlens.core.project import safe_folder_name, validate_project_root_dir
from gridlens.core.validation import ValidationError, is_windows_reserved_name


@pytest.mark.parametrize("name", ["CON", "con", "Nul.txt", "COM1", "lpt9 "])
def test_windows_device_names_are_reserved(name) -> None:
    assert is_windows_reserved_name(name)


@pytest.mark.parametrize("name", ["CONSOLE", "COM0", "Texas7k", "AUX_Case"])
def test_ordinary_names_are_not_reserved(name) -> None:
    assert not is_windows_reserved_name(name)


def test_a_project_named_for_a_device_gets_a_creatable_folder() -> None:
    assert safe_folder_name("CON") == "CON_Project"
    assert safe_folder_name("Nul") == "Nul_Project"
    assert safe_folder_name("Texas 7k") == "Texas_7k"


def test_windows_refuses_a_device_name_as_a_project_folder(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(project.processes, "WINDOWS", True)

    with pytest.raises(ValidationError, match="reserves the name"):
        validate_project_root_dir(tmp_path / "CON")


def test_a_folder_that_exists_in_another_case_is_refused(
        tmp_path, monkeypatch) -> None:
    existing = tmp_path / "Test"
    existing.mkdir()
    real_resolve = Path.resolve

    def case_insensitive_resolve(path, strict=False):
        # What Windows and macOS return: the spelling already on disk.
        if path.name == "test":
            return existing
        return real_resolve(path, strict)

    monkeypatch.setattr(Path, "resolve", case_insensitive_resolve)

    with pytest.raises(ValidationError, match="does not tell"):
        validate_project_root_dir(tmp_path / "test")


def test_the_same_spelling_is_the_same_project_folder(tmp_path) -> None:
    folder = tmp_path / "Test"
    folder.mkdir()

    assert validate_project_root_dir(folder) == folder.resolve()
