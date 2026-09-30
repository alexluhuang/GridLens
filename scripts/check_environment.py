"""Check that this machine can run GridLens: Python, Docker, and the GPU.

Run it with the Python that runs GridLens:

    python scripts/check_environment.py

On Linux it also explains Docker permission problems; on Windows it checks
that Docker Desktop runs Linux containers.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
MINIMUM_PYTHON = (3, 11)


def run(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, check=False, text=True, encoding="utf-8",
            errors="replace", stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return 127, f"{command[0]} not found"
    return result.returncode, result.stdout.strip()


def current_groups() -> str:
    code, output = run(["id"])
    if code == 0:
        return output
    return "unable to read current groups"


def group_entry(name: str) -> str:
    code, output = run(["getent", "group", name])
    if code == 0:
        return output
    return f"group {name!r} not found"


def docker_socket_status() -> str:
    socket = Path("/var/run/docker.sock")
    if not socket.exists():
        return "not found"
    code, output = run(["stat", "-c", "%A %U %G %u %g %n", str(socket)])
    if code == 0:
        return output
    return output or "unable to stat /var/run/docker.sock"


def gpu_status() -> tuple[bool, str]:
    """Return whether the CUDA runtime reports a device, and what it says."""
    try:
        from cupy.cuda import runtime
    except ImportError:
        if WINDOWS:
            return True, "not used: RAPIDS has no Windows build; CPU Dask"
        return False, "CuPy is not installed; install the analysis extra"
    try:
        count = runtime.getDeviceCount()
    except Exception as exc:
        return False, f"no usable device ({exc}); check nvidia-smi"
    return count > 0, f"{count} CUDA device(s)"


def engine_check() -> tuple[bool, str]:
    """Return whether the Docker engine answers and runs Linux containers."""
    code, output = run(
        ["docker", "version", "--format",
         "{{.Server.Version}} {{.Server.Os}}"])
    if code != 0:
        hint = " Start Docker Desktop." if WINDOWS else ""
        return False, output + hint
    version, _, server_os = output.partition(" ")
    if server_os and server_os != "linux":
        return False, (f"{version} runs {server_os} containers; switch "
                       "Docker Desktop to Linux containers")
    return True, version


def print_posix_permissions() -> None:
    """Explain why Docker may refuse this account, on Linux."""
    print("Docker permission diagnostics:")
    print(f"  Current identity: {current_groups()}")
    print(f"  docker group:     {group_entry('docker')}")
    print(f"  Docker socket:    {docker_socket_status()}")
    print()

    docker_group = group_entry("docker")
    identity = current_groups()
    socket = docker_socket_status()
    in_group = "docker" in identity
    if "docker:" in docker_group and not in_group:
        print("Recommended next step: run `newgrp docker`, or fully log out "
              "and log back in.")
    if "docker.sock" in socket and " docker " not in f" {socket} ":
        print("Socket note: Docker normally creates /var/run/docker.sock "
              "for group `docker`; if it is owned by another group, restart "
              "Docker and re-check the socket.")


def print_windows_docker() -> None:
    """Show which Docker endpoint the CLI uses, on Windows."""
    code, output = run(
        ["docker", "context", "inspect", "--format",
         "{{.Name}} {{.Endpoints.docker.Host}}"])
    print("Docker context:")
    print(f"  {output if code == 0 else 'unavailable: ' + output}")
    print()


def main() -> int:
    python_ok = sys.version_info >= MINIMUM_PYTHON
    docker = shutil.which("docker")
    checks = [
        ("Python", python_ok, sys.version.split()[0]),
        ("Operating system", True, platform.platform()),
        ("Architecture", True, platform.machine()),
        ("Docker on PATH", docker is not None, docker or "not found"),
    ]

    code, output = run(["docker", "--version"])
    checks.append(("Docker client", code == 0, output))
    checks.append(("Docker engine", *engine_check()))
    checks.append(("GPU", *gpu_status()))

    for name, ok, detail in checks:
        status = "OK" if ok else "PROBLEM"
        print(f"{status:8} {name}: {detail}")
    print()

    if WINDOWS:
        print_windows_docker()
    else:
        print_posix_permissions()

    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
