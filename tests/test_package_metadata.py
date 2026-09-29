from __future__ import annotations

from pathlib import Path
import re
import tomllib

from packaging.requirements import Requirement

import gridlens


ROOT = Path(__file__).resolve().parents[1]


def _project_metadata() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_package_version_matches_project_metadata() -> None:
    metadata = _project_metadata()

    assert gridlens.__version__ == metadata["version"]


def test_console_script_points_to_main_entrypoint() -> None:
    metadata = _project_metadata()

    assert metadata["scripts"]["gridlens"] == "gridlens.main:main"


def test_runtime_requirements_mirror_project_dependencies() -> None:
    metadata = _project_metadata()
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert requirements == metadata["dependencies"]


def _requirement_lines(relative_path: str) -> list[str]:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def test_analysis_requirements_mirror_the_analysis_extra() -> None:
    extras = _project_metadata()["optional-dependencies"]

    mirrored = _requirement_lines("requirements-analysis.txt")
    assert mirrored == extras["analysis"]


def test_python_floor_is_the_one_rapids_and_numpy_need() -> None:
    metadata = _project_metadata()

    assert metadata["requires-python"] == ">=3.11"
    classifiers = metadata["classifiers"]
    assert "Programming Language :: Python :: 3.10" not in classifiers


def test_gpu_extras_add_linux_only_rapids_to_the_cpu_stack() -> None:
    extras = _project_metadata()["optional-dependencies"]
    cpu = extras["analysis-cpu"]

    for name in ("analysis", "analysis-cu12"):
        stack = extras[name]
        assert stack[: len(cpu)] == cpu, name
        for text in stack[len(cpu):]:
            marker = Requirement(text).marker
            assert marker is not None, text
            assert marker.evaluate({"sys_platform": "linux"}), text
            assert not marker.evaluate({"sys_platform": "win32"}), text


def test_cpu_stack_installs_on_every_platform() -> None:
    cpu = _project_metadata()["optional-dependencies"]["analysis-cpu"]

    assert all(Requirement(text).marker is None for text in cpu)


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
