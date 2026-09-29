"""Provider-neutral subprocess, environment, and MCP-child helpers.

Every runtime adapter launches a vendor CLI the same way: an argument list with no shell, a minimal
environment, its own process group, and group termination on Stop or application exit. Keeping those
mechanics here means a new adapter adds no new process handling.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from gridlens.system import processes


PROBE_TIMEOUT_SECONDS = 10
# The console executable a frozen Windows build ships beside GridLens.exe.
CONSOLE_EXECUTABLE = "gridlens-cli.exe"
PROBE_OUTPUT_LIMIT = 16 * 1024
# The host variables a command-line program needs to start, find its own
# files, and reach the network. Nothing else of the host environment is
# passed on.
POSIX_ENVIRONMENT = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR")
# A Windows program also needs SYSTEMROOT, without which Winsock and many
# system libraries fail to load; the profile folders, where programs keep
# their settings and credentials and GridLens keeps settings.json; and TEMP.
WINDOWS_ENVIRONMENT = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC",
    "TEMP", "TMP", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "USERNAME", "USERDOMAIN", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
)


def _host_variables() -> dict[str, str]:
    """Return the host variables that this platform's programs need."""
    names = WINDOWS_ENVIRONMENT if processes.WINDOWS else POSIX_ENVIRONMENT
    return {name: os.environ[name] for name in names if name in os.environ}


def minimal_environment(*, loopback_only: bool = True) -> dict[str, str]:
    """Build the smallest environment a CLI needs; never copy the host environment wholesale."""
    environment = _host_variables()
    environment["PYTHONUNBUFFERED"] = "1"
    if loopback_only:
        # A proxy must never redirect inference that the route classification calls local.
        environment.update(NO_PROXY="*", no_proxy="*")
    # PyInstaller modifies its own library search path; an external CLI needs the host libraries.
    if os.environ.get("LD_LIBRARY_PATH_ORIG"):
        environment["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
    return environment


def gridlens_command(*arguments: str) -> list[str]:
    """Return the argv that runs GridLens with arguments, for the source and frozen entry points."""
    if getattr(sys, "frozen", False):
        return [_frozen_executable(), *arguments]
    return [sys.executable, "-m", "gridlens", *arguments]


def _frozen_executable() -> str:
    """Return the frozen executable that runs GridLens's stdio entry points.

    A windowed Windows executable has no reliable standard streams, so a
    frozen Windows build runs the MCP server, job workers, and the tool CLI
    from its console executable, which GridLens starts with no window.
    """
    if processes.WINDOWS:
        helper = Path(sys.executable).with_name(CONSOLE_EXECUTABLE)
        if helper.is_file():
            return str(helper)
    return sys.executable


def mcp_command() -> list[str]:
    """Return the argv that starts the GridLens MCP server, for the source and frozen entry points."""
    return gridlens_command("--mcp-server")


def mcp_server_environment(session_directory: Path) -> dict[str, str]:
    """Environment for the MCP child: the session capability file, and nothing else of substance."""
    environment = {"GRIDLENS_AGENT_CONTEXT": str(session_directory / "context.json")}
    if processes.WINDOWS:
        # A runtime may start its MCP server with only these variables, and
        # on Windows the server could not then open a socket or find the
        # GridLens settings.
        environment.update(_host_variables())
    if not getattr(sys, "frozen", False):
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    return environment


def terminate_process(process: subprocess.Popen) -> None:
    """Terminate the CLI and its MCP children, including after the parent has exited."""
    processes.terminate(process)


def run_probe(argv: list[str], *, timeout: float = PROBE_TIMEOUT_SECONDS, loopback_only: bool = True) -> tuple[int, bytes]:
    """Run a bounded, non-interactive version or login probe. Never records credentials."""
    process = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=minimal_environment(loopback_only=loopback_only),
        **processes.new_group_options(),
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        output = b""
    finally:
        terminate_process(process)
    code = process.returncode if process.returncode is not None else -1
    return code, output[:PROBE_OUTPUT_LIMIT]


def probe_version(executable: str, pattern, *, argument: str = "--version") -> str:
    """Return the first version captured by pattern, or "unknown" when the CLI answers differently."""
    _, output = run_probe([executable, argument])
    match = pattern.search(output)
    return match[1].decode(errors="replace") if match else "unknown"
