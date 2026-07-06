from __future__ import annotations

import os
from pathlib import Path
import shlex

from gridlens.core.run_manifest import detect_docker_platform
from gridlens.core.validation import (
    validate_docker_image,
    validate_executable,
    validate_mpi_processes,
)


DOCKER_BASE_COMMAND = ["docker", "run", "--rm"]
CONTAINER_WORKSPACE = "/app/workspace"
CONTAINER_HOME_ENV = "HOME=/tmp"
MPI_EXECUTABLE = "mpirun"


def _split_extra_args(extra_docker_args: str | list[str] | None) -> list[str]:
    if not extra_docker_args:
        return []
    if isinstance(extra_docker_args, list):
        return [str(item) for item in extra_docker_args]
    return shlex.split(extra_docker_args)


def build_gridpack_docker_command(
    work_dir: str | Path,
    image: str,
    executable: str,
    xml_filename: str,
    mpi_processes: int,
    network_mode: str = "none",
    pull_policy: str = "never",
    use_host_user: bool = True,
    use_platform_flag: bool = True,
    memory_limit: str = "",
    extra_docker_args: str | list[str] | None = None,
    executable_args: list[str] | None = None,
) -> list[str]:
    resolved_work_dir = Path(work_dir).expanduser().resolve()
    if not resolved_work_dir.exists():
        raise FileNotFoundError(f"Work directory does not exist: {resolved_work_dir}")

    image = validate_docker_image(image)
    executable = validate_executable(executable)
    mpi_processes = validate_mpi_processes(int(mpi_processes))
    xml_filename = Path(xml_filename).name
    if not xml_filename:
        raise ValueError("XML file name is required.")

    cmd = list(DOCKER_BASE_COMMAND)

    if pull_policy:
        cmd.append(f"--pull={pull_policy}")

    if network_mode:
        cmd += ["--network", network_mode]

    if use_platform_flag:
        platform_value = detect_docker_platform()
        if platform_value:
            cmd += ["--platform", platform_value]

    if use_host_user and hasattr(os, "getuid") and hasattr(os, "getgid"):
        cmd += ["-u", f"{os.getuid()}:{os.getgid()}"]
        cmd += ["-e", CONTAINER_HOME_ENV]

    if memory_limit.strip():
        cmd += ["--memory", memory_limit.strip()]

    cmd += _split_extra_args(extra_docker_args)
    cmd += [
        "-v",
        f"{resolved_work_dir}:{CONTAINER_WORKSPACE}",
        "-w",
        CONTAINER_WORKSPACE,
        image,
        MPI_EXECUTABLE,
        "-n",
        str(mpi_processes),
        executable,
        xml_filename,
    ]

    if executable_args:
        cmd += [str(arg) for arg in executable_args]

    return cmd
