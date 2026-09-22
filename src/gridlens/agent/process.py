"""Provider-neutral subprocess, environment, and MCP-child helpers.

Every runtime adapter launches a vendor CLI the same way: an argument list with no shell, a minimal
environment, its own process group, and group termination on Stop or application exit. Keeping those
mechanics here means a new adapter adds no new process handling.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys


PROBE_TIMEOUT_SECONDS = 10
PROBE_OUTPUT_LIMIT = 16 * 1024


def minimal_environment(*, loopback_only: bool = True) -> dict[str, str]:
    """Build the smallest environment a CLI needs; never copy the host environment wholesale."""
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    environment["PYTHONUNBUFFERED"] = "1"
    if loopback_only:
        # A proxy must never redirect inference that the route classification calls local.
        environment.update(NO_PROXY="*", no_proxy="*")
    # PyInstaller modifies its own library search path; an external CLI needs the host libraries.
    if os.environ.get("LD_LIBRARY_PATH_ORIG"):
        environment["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
    return environment


def mcp_command() -> list[str]:
    """Return the argv that starts the GridLens MCP server, for the source and frozen entry points."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--mcp-server"]
    return [sys.executable, "-m", "gridlens", "--mcp-server"]


def mcp_server_environment(session_directory: Path) -> dict[str, str]:
    """Environment for the MCP child: the session capability file, and nothing else of substance."""
    environment = {"GRIDLENS_AGENT_CONTEXT": str(session_directory / "context.json")}
    if not getattr(sys, "frozen", False):
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    return environment


def terminate_process(process: subprocess.Popen) -> None:
    """Terminate the CLI and its MCP children, including after the parent has exited."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def run_probe(argv: list[str], *, timeout: float = PROBE_TIMEOUT_SECONDS, loopback_only: bool = True) -> tuple[int, bytes]:
    """Run a bounded, non-interactive version or login probe. Never records credentials."""
    process = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=minimal_environment(loopback_only=loopback_only), start_new_session=True,
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
