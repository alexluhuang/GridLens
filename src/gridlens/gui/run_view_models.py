from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from gridlens.core import sensitivity
from gridlens.core.app_settings import AppSettings
from gridlens.core.project import ProjectData
from gridlens.core.validation import (
    ValidationError,
    validate_docker_image,
    validate_mpi_processes,
)
from gridlens.runner.gridpack_runner import GridpackRunRequest, effective_gridpack_container_name


VALID_PULL_POLICIES = frozenset({"never", "missing", "always"})
# GridLens runs GridPACK's contingency analysis, so every run uses its executable.
GRIDPACK_EXECUTABLE = "ca.x"


@dataclass(frozen=True, slots=True)
class RunFormValues:
    """The Run tab's settings for one GridPACK run.

    Every run uses ca.x, with the container's network disabled, the detected platform flag, and output
    files written as the current user. Those fields stay so that the form a job record saved still loads,
    and validation resets them to these values whatever the record says.
    """
    image: str
    mpi_processes: int
    pull_policy: str
    memory_limit: str = ""
    extra_docker_args: str = ""
    executable: str = GRIDPACK_EXECUTABLE
    network_disabled: bool = True
    use_platform_flag: bool = True
    use_host_user: bool = True

    @property
    def network_mode(self) -> str:
        return "none" if self.network_disabled else ""


def validate_run_form_values(values: RunFormValues) -> RunFormValues:
    image = validate_docker_image(values.image)
    mpi_processes = validate_mpi_processes(values.mpi_processes)
    pull_policy = values.pull_policy.strip()
    if pull_policy not in VALID_PULL_POLICIES:
        allowed = ", ".join(sorted(VALID_PULL_POLICIES))
        raise ValidationError(f"Docker pull policy must be one of: {allowed}.")

    return RunFormValues(
        image=image,
        mpi_processes=mpi_processes,
        pull_policy=pull_policy,
        memory_limit=values.memory_limit.strip(),
        extra_docker_args=values.extra_docker_args.strip(),
    )


def apply_run_form_values_to_settings(settings: AppSettings, values: RunFormValues) -> AppSettings:
    normalized = validate_run_form_values(values)
    settings.default_gridpack_image = normalized.image
    settings.default_mpi_processes = normalized.mpi_processes
    settings.docker_pull_policy = normalized.pull_policy
    settings.memory_limit = normalized.memory_limit
    settings.extra_docker_args = normalized.extra_docker_args
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
        container_name=effective_gridpack_container_name(run_dir, normalized.extra_docker_args),
    )


def build_sensitivity_run_request(
    project_data: ProjectData,
    run_dir: Path,
    values: RunFormValues,
    case: sensitivity.PatchedCase,
) -> GridpackRunRequest:
    """Write an edited case into a run folder; return a request to run it."""
    request = build_gridpack_run_request(project_data, run_dir, values)
    xml_file_name = sensitivity.write_run_inputs(project_data, run_dir, case)
    note = sensitivity.run_note(case)
    return replace(request, xml_filename=xml_file_name, notes=note)


__all__ = [
    "GRIDPACK_EXECUTABLE",
    "RunFormValues",
    "apply_run_form_values_to_settings",
    "build_gridpack_run_request",
    "build_sensitivity_run_request",
    "validate_run_form_values",
]
