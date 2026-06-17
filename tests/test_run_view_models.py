from __future__ import annotations

from pathlib import Path

import pytest

from gridpack_workbench.core.app_settings import AppSettings
from gridpack_workbench.core.project import ProjectData
from gridpack_workbench.core.validation import ValidationError
from gridpack_workbench.gui.run_view_models import (
    RunFormValues,
    apply_run_form_values_to_settings,
    build_gridpack_run_request,
    validate_run_form_values,
)


def test_apply_run_form_values_normalizes_settings() -> None:
    settings = AppSettings()
    values = RunFormValues(
        image=" pnnl/gridpack:test ",
        executable=" ca.x ",
        mpi_processes=8,
        pull_policy="missing",
        network_disabled=False,
        use_platform_flag=False,
        use_host_user=False,
        memory_limit=" 16g ",
        extra_docker_args=" --ipc=host ",
    )

    apply_run_form_values_to_settings(settings, values)

    assert settings.default_gridpack_image == "pnnl/gridpack:test"
    assert settings.default_executable == "ca.x"
    assert settings.default_mpi_processes == 8
    assert settings.docker_pull_policy == "missing"
    assert settings.docker_network_mode == ""
    assert settings.use_platform_flag is False
    assert settings.use_host_user is False
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
    values = RunFormValues(
        image=" pnnl/gridpack:test ",
        executable=" ca.x ",
        mpi_processes=4,
        pull_policy="never",
        network_disabled=True,
        use_platform_flag=True,
        use_host_user=True,
    )

    request = build_gridpack_run_request(project_data, tmp_path / "run", values)

    assert request.project_data is project_data
    assert request.run_dir == tmp_path / "run"
    assert request.image == "pnnl/gridpack:test"
    assert request.executable == "ca.x"
    assert request.xml_filename == "input.xml"
    assert request.mpi_processes == 4
    assert request.network_mode == "none"


def test_run_form_validation_rejects_unknown_pull_policy() -> None:
    values = RunFormValues(
        image="pnnl/gridpack:test",
        executable="ca.x",
        mpi_processes=1,
        pull_policy="sometimes",
        network_disabled=True,
        use_platform_flag=True,
        use_host_user=True,
    )

    with pytest.raises(ValidationError, match="pull policy"):
        validate_run_form_values(values)
