from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

from gridlens.runner import docker_probe
from gridlens.runner.docker_probe import (
    docker_client_available, docker_engine_available, image_exists,
    run_command)


def completed(command: list[str], returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def test_docker_client_available_reports_missing_binary() -> None:
    with patch("gridlens.runner.docker_probe.run_command", side_effect=FileNotFoundError):
        result = docker_client_available()

    assert result.ok is False
    assert result.message == "Docker was not found on PATH."


def test_docker_engine_available_formats_success_message() -> None:
    with patch(
        "gridlens.runner.docker_probe.run_command",
        return_value=completed(["docker"], 0, stdout="29.2.1\n"),
    ):
        result = docker_engine_available()

    assert result.ok is True
    assert result.message == "Docker Engine 29.2.1"


def test_docker_engine_available_uses_fallback_for_empty_failure_output() -> None:
    with patch(
        "gridlens.runner.docker_probe.run_command",
        return_value=completed(["docker"], 1),
    ):
        result = docker_engine_available()

    assert result.ok is False
    assert result.message == "Docker Engine is not reachable."


def test_image_exists_reports_timeout_with_image_name() -> None:
    with patch(
        "gridlens.runner.docker_probe.run_command",
        side_effect=subprocess.TimeoutExpired(["docker"], timeout=30),
    ):
        result = image_exists("pnnl/gridpack:latest")

    assert result.ok is False
    assert result.message == "Timed out while checking image pnnl/gridpack:latest."


def test_image_exists_reports_local_image_success() -> None:
    with patch(
        "gridlens.runner.docker_probe.run_command",
        return_value=completed(["docker"], 0, stdout="[]\n"),
    ):
        result = image_exists("pnnl/gridpack:latest")

    assert result.ok is True
    assert result.message == "Image is available locally: pnnl/gridpack:latest"


def test_probe_output_is_decoded_as_utf8_whatever_the_locale() -> None:
    # U+00C1 is C3 81 in UTF-8, and 0x81 is undefined in Windows-1252.
    text = "\u00c5ngstr\u00f6m \u00c1 \u2026"
    code = f"import sys; sys.stdout.buffer.write({text!r}.encode('utf-8'))"

    result = run_command([sys.executable, "-c", code])

    assert result.stdout == text


def test_undecodable_probe_output_is_replaced_rather_than_raised() -> None:
    code = "import sys; sys.stdout.buffer.write(b'ok \\xff')"

    result = run_command([sys.executable, "-c", code])

    assert result.stdout == "ok \ufffd"


def test_docker_engine_running_windows_containers_is_a_problem() -> None:
    windows = completed(["docker"], 0, stdout="29.2.1 windows\n")
    with patch("gridlens.runner.docker_probe.run_command",
               return_value=windows):
        result = docker_engine_available()

    assert result.ok is False
    assert "switch Docker Desktop to Linux containers" in result.message


def test_docker_engine_running_linux_containers_is_ready() -> None:
    linux = completed(["docker"], 0, stdout="29.2.1 linux\n")
    with patch("gridlens.runner.docker_probe.run_command",
               return_value=linux):
        result = docker_engine_available()

    assert (result.ok, result.message) == (True, "Docker Engine 29.2.1")


def test_unreachable_engine_on_windows_says_to_start_docker_desktop(
        monkeypatch) -> None:
    monkeypatch.setattr(docker_probe.processes, "WINDOWS", True)
    unreachable = completed(["docker"], 1, stderr="error during connect")
    with patch("gridlens.runner.docker_probe.run_command",
               return_value=unreachable):
        result = docker_engine_available()

    assert result.ok is False
    assert result.message.endswith(docker_probe.START_DOCKER_DESKTOP)
