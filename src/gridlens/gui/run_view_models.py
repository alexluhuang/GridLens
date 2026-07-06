from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gridlens.core.app_settings import AppSettings
from gridlens.core.project import ProjectData
from gridlens.core.validation import (
    ValidationError,
    validate_docker_image,
    validate_executable,
    validate_mpi_processes,
)
from gridlens.runner.gridpack_runner import GridpackRunRequest


VALID_PULL_POLICIES = frozenset({"never", "missing", "always"})


@dataclass(frozen=True, slots=True)
class RunFormValues:
    image: str
    executable: str
    mpi_processes: int
    pull_policy: str
    network_disabled: bool
    use_platform_flag: bool
    use_host_user: bool
    memory_limit: str = ""
    extra_docker_args: str = ""

    @property
    def network_mode(self) -> str:
        return "none" if self.network_disabled else ""


def validate_run_form_values(values: RunFormValues) -> RunFormValues:
    image = validate_docker_image(values.image)
    executable = validate_executable(values.executable)
    mpi_processes = validate_mpi_processes(values.mpi_processes)
    pull_policy = values.pull_policy.strip()
    if pull_policy not in VALID_PULL_POLICIES:
        allowed = ", ".join(sorted(VALID_PULL_POLICIES))
        raise ValidationError(f"Docker pull policy must be one of: {allowed}.")

    return RunFormValues(
        image=image,
        executable=executable,
        mpi_processes=mpi_processes,
        pull_policy=pull_policy,
        network_disabled=values.network_disabled,
        use_platform_flag=values.use_platform_flag,
        use_host_user=values.use_host_user,
        memory_limit=values.memory_limit.strip(),
        extra_docker_args=values.extra_docker_args.strip(),
    )


def apply_run_form_values_to_settings(settings: AppSettings, values: RunFormValues) -> AppSettings:
    normalized = validate_run_form_values(values)
    settings.default_gridpack_image = normalized.image
    settings.default_executable = normalized.executable
    settings.default_mpi_processes = normalized.mpi_processes
    settings.docker_pull_policy = normalized.pull_policy
    settings.use_platform_flag = normalized.use_platform_flag
    settings.use_host_user = normalized.use_host_user
    settings.memory_limit = normalized.memory_limit
    settings.extra_docker_args = normalized.extra_docker_args
    settings.docker_network_mode = normalized.network_mode
    return settings


def build_gridpack_run_request(
    project_data: ProjectData,
    run_dir: Path,
    values: RunFormValues,
) -> GridpackRunRequest:
    normalized = validate_run_form_values(values)
    return GridpackRunRequest(
        project_data=project_data,
        run_dir=run_dir,
        image=normalized.image,
        executable=normalized.executable,
        xml_filename=project_data.xml_file_name,
        mpi_processes=normalized.mpi_processes,
        network_mode=normalized.network_mode,
        pull_policy=normalized.pull_policy,
        use_host_user=normalized.use_host_user,
        use_platform_flag=normalized.use_platform_flag,
        memory_limit=normalized.memory_limit,
        extra_docker_args=normalized.extra_docker_args,
    )


__all__ = [
    "RunFormValues",
    "apply_run_form_values_to_settings",
    "build_gridpack_run_request",
    "validate_run_form_values",
]
