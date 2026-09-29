from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
import subprocess

from gridlens.system import processes


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    message: str


SuccessMessage = Callable[[str], str]
# Where the docker CLI finds the daemon when nothing else names one.
DEFAULT_ENDPOINT = (
    "npipe:////./pipe/docker_engine" if processes.WINDOWS
    else "unix:///var/run/docker.sock")
# A daemon reached through one of these runs on this machine, so the files a
# container mounts are this machine's files.
LOCAL_SCHEMES = ("unix://", "npipe://")
START_DOCKER_DESKTOP = "Start Docker Desktop, then check again."


def run_command(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
        **processes.no_window_options(),
    )


def _probe_docker_command(
    command: list[str],
    timeout_message: str,
    success_message: SuccessMessage,
    failure_message: str,
) -> ProbeResult:
    try:
        result = run_command(command)
    except FileNotFoundError:
        return ProbeResult(False, "Docker was not found on PATH.")
    except subprocess.TimeoutExpired:
        return ProbeResult(False, timeout_message)

    output = (result.stdout or result.stderr).strip()
    if result.returncode == 0:
        return ProbeResult(True, success_message(output))
    return ProbeResult(False, output or failure_message)


def docker_client_available() -> ProbeResult:
    return _probe_docker_command(
        ["docker", "--version"],
        timeout_message="Docker version check timed out.",
        success_message=lambda output: output,
        failure_message="Docker client is not available.",
    )


def docker_engine_available() -> ProbeResult:
    """Report whether the Docker engine answers and runs Linux containers.

    GridPACK images are Linux images, and Docker Desktop can be switched to
    Windows containers, where every one of them fails.
    """
    result = _probe_docker_command(
        ["docker", "version", "--format",
         "{{.Server.Version}} {{.Server.Os}}"],
        timeout_message="Docker engine check timed out.",
        success_message=lambda output: output,
        failure_message="Docker Engine is not reachable.",
    )
    if not result.ok:
        if processes.WINDOWS:
            message = f"{result.message} {START_DOCKER_DESKTOP}"
            return ProbeResult(False, message)
        return result
    version, _, server_os = result.message.partition(" ")
    if server_os.strip() not in ("", "linux"):
        return ProbeResult(
            False,
            f"Docker Engine {version} runs {server_os.strip()} containers. "
            "GridPACK needs Linux containers: switch Docker Desktop to "
            "Linux containers.")
    return ProbeResult(True, f"Docker Engine {version}")


def local_docker_endpoint() -> str:
    """Return the endpoint of the Docker daemon this user's CLI talks to.

    DOCKER_HOST wins, as it does for the CLI; then the endpoint of the
    current docker context; then the platform's default. Raises ValueError
    when the daemon is reached over the network, because a container there
    would mount another machine's files.
    """
    endpoint = os.environ.get("DOCKER_HOST", "").strip()
    if not endpoint:
        endpoint = _context_endpoint() or DEFAULT_ENDPOINT
    if not endpoint.startswith(LOCAL_SCHEMES):
        raise ValueError(f"Docker is reached over the network ({endpoint}).")
    return endpoint


def _context_endpoint() -> str:
    """Return the Docker endpoint of the current docker context, or ""."""
    command = ["docker", "context", "inspect", "--format",
               "{{.Endpoints.docker.Host}}"]
    try:
        result = run_command(command, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def image_exists(image: str) -> ProbeResult:
    return _probe_docker_command(
        ["docker", "image", "inspect", image],
        timeout_message=f"Timed out while checking image {image}.",
        success_message=lambda output: f"Image is available locally: {image}",
        failure_message=f"Image is not available locally: {image}",
    )
