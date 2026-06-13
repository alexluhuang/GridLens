from __future__ import annotations

import platform
import shutil
import subprocess
import sys


def run(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return 127, f"{command[0]} not found"
    return result.returncode, result.stdout.strip()


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

    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
