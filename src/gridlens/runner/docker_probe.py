from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import subprocess


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    message: str


SuccessMessage = Callable[[str], str]


def run_command(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
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
    return _probe_docker_command(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        timeout_message="Docker engine check timed out.",
        success_message=lambda output: f"Docker Engine {output}",
        failure_message="Docker Engine is not reachable.",
    )


def image_exists(image: str) -> ProbeResult:
    return _probe_docker_command(
        ["docker", "image", "inspect", image],
        timeout_message=f"Timed out while checking image {image}.",
        success_message=lambda output: f"Image is available locally: {image}",
        failure_message=f"Image is not available locally: {image}",
    )
