from __future__ import annotations

import subprocess
from unittest.mock import patch

from gridpack_workbench.runner.docker_probe import docker_client_available, docker_engine_available, image_exists


def completed(command: list[str], returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def test_docker_client_available_reports_missing_binary() -> None:
    with patch("gridpack_workbench.runner.docker_probe.run_command", side_effect=FileNotFoundError):
        result = docker_client_available()

    assert result.ok is False
    assert result.message == "Docker was not found on PATH."


def test_docker_engine_available_formats_success_message() -> None:
    with patch(
        "gridpack_workbench.runner.docker_probe.run_command",
        return_value=completed(["docker"], 0, stdout="29.2.1\n"),
    ):
        result = docker_engine_available()

    assert result.ok is True
    assert result.message == "Docker Engine 29.2.1"


def test_docker_engine_available_uses_fallback_for_empty_failure_output() -> None:
    with patch(
        "gridpack_workbench.runner.docker_probe.run_command",
        return_value=completed(["docker"], 1),
    ):
        result = docker_engine_available()

    assert result.ok is False
    assert result.message == "Docker Engine is not reachable."


def test_image_exists_reports_timeout_with_image_name() -> None:
    with patch(
        "gridpack_workbench.runner.docker_probe.run_command",
        side_effect=subprocess.TimeoutExpired(["docker"], timeout=30),
    ):
        result = image_exists("pnnl/gridpack:latest")

    assert result.ok is False
    assert result.message == "Timed out while checking image pnnl/gridpack:latest."


def test_image_exists_reports_local_image_success() -> None:
    with patch(
        "gridpack_workbench.runner.docker_probe.run_command",
        return_value=completed(["docker"], 0, stdout="[]\n"),
    ):
        result = image_exists("pnnl/gridpack:latest")

    assert result.ok is True
    assert result.message == "Image is available locally: pnnl/gridpack:latest"
