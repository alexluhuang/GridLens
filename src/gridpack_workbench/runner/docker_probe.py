from __future__ import annotations

from dataclasses import dataclass
import subprocess


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    message: str


def run_command(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
    )


def docker_client_available() -> ProbeResult:
    try:
        result = run_command(["docker", "--version"])
    except FileNotFoundError:
        return ProbeResult(False, "Docker was not found on PATH.")
    except subprocess.TimeoutExpired:
        return ProbeResult(False, "Docker version check timed out.")

    output = (result.stdout or result.stderr).strip()
    return ProbeResult(result.returncode == 0, output)


def docker_engine_available() -> ProbeResult:
    try:
        result = run_command(["docker", "version", "--format", "{{.Server.Version}}"])
    except FileNotFoundError:
        return ProbeResult(False, "Docker was not found on PATH.")
    except subprocess.TimeoutExpired:
        return ProbeResult(False, "Docker engine check timed out.")

    output = (result.stdout or result.stderr).strip()
    if result.returncode == 0:
        return ProbeResult(True, f"Docker Engine {output}")
    return ProbeResult(False, output or "Docker Engine is not reachable.")


def image_exists(image: str) -> ProbeResult:
    try:
        result = run_command(["docker", "image", "inspect", image])
    except FileNotFoundError:
        return ProbeResult(False, "Docker was not found on PATH.")
    except subprocess.TimeoutExpired:
        return ProbeResult(False, f"Timed out while checking image {image}.")

    if result.returncode == 0:
        return ProbeResult(True, f"Image is available locally: {image}")
    return ProbeResult(False, (result.stderr or result.stdout).strip() or f"Image is not available locally: {image}")
