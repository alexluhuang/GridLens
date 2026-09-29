from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridlens.core.app_settings import AppSettings
from gridlens.core.project import ProjectData
from gridlens.core.validation import ValidationError
from gridlens.gui.run_view_models import (
    GRIDPACK_EXECUTABLE,
    RunFormValues,
    apply_run_form_values_to_settings,
    build_gridpack_run_request,
    validate_run_form_values,
)


def test_apply_run_form_values_normalizes_settings() -> None:
    settings = AppSettings()
    values = RunFormValues(
        image=" pnnl/gridpack:test ",
        mpi_processes=8,
        pull_policy="missing",
        memory_limit=" 16g ",
        extra_docker_args=" --ipc=host ",
    )

    apply_run_form_values_to_settings(settings, values)

    assert settings.default_gridpack_image == "pnnl/gridpack:test"
    assert settings.default_mpi_processes == 8
    assert settings.docker_pull_policy == "missing"
    assert settings.memory_limit == "16g"
    assert settings.extra_docker_args == "--ipc=host"


def test_build_gridpack_run_request_uses_project_xml_and_normalized_values(tmp_path: Path) -> None:
    project_data = ProjectData(
        name="Pilot",
        root_dir=str(tmp_path / "project"),
        created_at="2026-06-16T00:00:00-07:00",
        updated_at="2026-06-16T00:00:00-07:00",
        xml_file_name="input.xml",
    )
    values = RunFormValues(image=" pnnl/gridpack:test ", mpi_processes=4, pull_policy="never")

    request = build_gridpack_run_request(project_data, tmp_path / "run", values)

    assert request.project_data is project_data
    assert request.run_dir == tmp_path / "run"
    assert request.image == "pnnl/gridpack:test"
    assert request.executable == "ca.x"
    assert request.xml_filename == "input.xml"
    assert request.mpi_processes == 4
    assert request.network_mode == "none"
    assert request.use_platform_flag is True
    assert request.use_host_user is True
    assert request.container_name == "gridlens-run"


def test_run_form_always_runs_ca_x_without_network_as_the_current_user() -> None:
    """A saved job form that names another executable or turns a safeguard off still runs ca.x with all three on."""
    saved = {"image": "pnnl/gridpack:test", "executable": "powerflow.x", "mpi_processes": 2, "pull_policy": "never",
             "network_disabled": False, "use_platform_flag": False, "use_host_user": False, "memory_limit": "", "extra_docker_args": ""}

    values = validate_run_form_values(RunFormValues(**saved))

    assert values.executable == GRIDPACK_EXECUTABLE == "ca.x"
    assert (values.network_mode, values.use_platform_flag, values.use_host_user) == ("none", True, True)


def test_settings_saved_with_the_removed_run_options_still_load(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"default_gridpack_image": "pnnl/gridpack:old", "default_executable": "powerflow.x",
                                "docker_network_mode": "", "use_platform_flag": False, "use_host_user": False}), encoding="utf-8")

    settings = AppSettings.load(path)

    assert settings.default_gridpack_image == "pnnl/gridpack:old"
    assert not hasattr(settings, "default_executable")


def test_run_form_validation_rejects_unknown_pull_policy() -> None:
    values = RunFormValues(image="pnnl/gridpack:test", mpi_processes=1, pull_policy="sometimes")

    with pytest.raises(ValidationError, match="pull policy"):
        validate_run_form_values(values)
