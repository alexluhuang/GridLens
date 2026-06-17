from __future__ import annotations

from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - used on Python 3.10.
    import tomli as tomllib

import gridpack_workbench


ROOT = Path(__file__).resolve().parents[1]


def _project_metadata() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_package_version_matches_project_metadata() -> None:
    metadata = _project_metadata()

    assert gridpack_workbench.__version__ == metadata["version"]


def test_console_script_points_to_main_entrypoint() -> None:
    metadata = _project_metadata()

    assert metadata["scripts"]["gridpack-workbench"] == "gridpack_workbench.main:main"


def test_runtime_requirements_mirror_project_dependencies() -> None:
    metadata = _project_metadata()
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert requirements == metadata["dependencies"]


def test_readme_local_documentation_links_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    local_links = [
        match.group("target")
        for match in re.finditer(r"\[[^\]]+\]\((?P<target>[^)]+)\)", readme)
        if not match.group("target").startswith(("http://", "https://", "#"))
    ]

    assert local_links
    for link in local_links:
        assert (ROOT / link).exists(), link
