from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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


def main() -> int:
    checks = []
    checks.append(("Python", True, sys.version.split()[0]))
    checks.append(("Architecture", True, platform.machine()))
    checks.append(("Docker on PATH", shutil.which("docker") is not None, shutil.which("docker") or "not found"))

    code, output = run(["docker", "--version"])
    checks.append(("Docker client", code == 0, output))

    code, output = run(["docker", "version", "--format", "{{.Server.Version}}"])
    checks.append(("Docker engine", code == 0, output))

    for name, ok, detail in checks:
        status = "OK" if ok else "PROBLEM"
        print(f"{status:8} {name}: {detail}")

    print()
    print("Docker permission diagnostics:")
    print(f"  Current identity: {current_groups()}")
    print(f"  docker group:     {group_entry('docker')}")
    print(f"  Docker socket:    {docker_socket_status()}")
    print()

    docker_group = group_entry("docker")
    identity = current_groups()
    socket = docker_socket_status()
    if "docker:" in docker_group and "docker" in docker_group and "docker" not in identity:
        print("Recommended next step: run `newgrp docker`, or fully log out and log back in.")
    if "docker.sock" in socket and " docker " not in f" {socket} ":
        print("Socket note: Docker normally creates /var/run/docker.sock for group `docker`; if it is owned by another group, restart Docker and re-check the socket.")

    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
