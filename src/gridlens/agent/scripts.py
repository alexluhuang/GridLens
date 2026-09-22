"""Proposals for generated analysis code, and the sandbox that runs an approved one.

The split here is deliberate and is the whole safety argument. `save_proposal` is reachable from a tool,
so the model can write code, and it only ever writes a file. `execute_proposal` is reachable only from the
review dialog, requires the SHA-256 of the exact reviewed bytes, and snapshots those bytes so that editing
the proposal afterward cannot change what runs.

The container the script runs in has no network, no GPU, a read-only view of one run, and limits on CPU,
memory, processes, file size, and wall-clock time. Its output is recorded as untrusted, because nothing
deterministic has checked it.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import threading
import time
from uuid import uuid4

from gridlens.agent.policy import AgentError
from gridlens.agent.process import minimal_environment, terminate_process
from gridlens.agent.session import SessionContext, append_event, read_json, scoped_path, timestamp, write_json


MAX_SCRIPT_BYTES = 24 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
DOCKER_HOST = "unix:///var/run/docker.sock"


READ_CHUNK_BYTES = 8192
CREATE_TIMEOUT_SECONDS = 20
INSPECT_TIMEOUT_SECONDS = 10
REMOVE_TIMEOUT_SECONDS = 15
POLL_SECONDS = 0.1


def _require_sandbox_image(executable: str, image: str, environment: dict) -> None:
    """Refuse any image that is not the separately prepared analysis sandbox.

    The label is the check, not the name. GridLens passes --pull=never, so an image that is absent or was
    built for another purpose has to be rejected here rather than discovered inside the container.
    """
    inspection = subprocess.run(
        [executable, "--host", DOCKER_HOST, "image", "inspect", image, "--format", '{{index .Config.Labels "org.gridlens.purpose"}}'],
        capture_output=True, timeout=INSPECT_TIMEOUT_SECONDS, env=environment,
    )
    if inspection.returncode or inspection.stdout.strip() != b"generated-analysis":
        raise AgentError("SANDBOX_IMAGE_REQUIRED", "Prepare a pinned image from packaging/agent/Dockerfile (source checkout) or /usr/share/doc/gridlens/agent-sandbox/Dockerfile (installed package). GridLens never pulls an image for script execution.")


def _stream_bounded_output(process, output: bytearray, cancelled, deadline: float) -> None:
    """Collect the container's output, stopping on cancellation, the deadline, or the size cap.

    The cap is enforced on the way in rather than afterward, so a runaway script cannot fill memory before
    anyone notices it exceeded the limit.
    """
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            if cancelled.is_set():
                raise AgentError("CANCELLED", "Script execution cancelled.")
            if time.monotonic() >= deadline:
                raise AgentError("TIMEOUT", "The script exceeded its wall-clock limit.")
            for key, _ in selector.select(POLL_SECONDS):
                chunk = os.read(key.fileobj.fileno(), READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                remaining = MAX_OUTPUT_BYTES - len(output)
                output.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    raise AgentError("OUTPUT_LIMIT", "The script exceeded its output limit.")


def _remove_container(executable: str, name: str, environment: dict) -> bool:
    """Remove the container and report whether it is gone. Never raises, so cleanup cannot mask a result."""
    try:
        removal = subprocess.run(
            [executable, "--host", DOCKER_HOST, "rm", "--force", name],
            capture_output=True, timeout=REMOVE_TIMEOUT_SECONDS, env=environment,
        )
        return removal.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def save_proposal(context: SessionContext, run_id: str, purpose: str, code: str) -> dict:
    """Save a model-proposed script for review. This never executes anything."""
    context.run(run_id)
    if not purpose.strip() or len(purpose) > 2000 or len(code.encode()) > MAX_SCRIPT_BYTES:
        raise AgentError("INVALID_PROPOSAL", "Provide a purpose under 2,000 characters and Python code under 24 KiB.")
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise AgentError("INVALID_PROPOSAL", "The proposed Python script has a syntax error; correct it before saving.") from exc
    directory = scoped_path(context.directory, "generated", directory=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    if len(list(directory.glob("*.json"))) >= 30:
        raise AgentError("SESSION_LIMIT", "Start a new session before proposing more scripts.")
    identifier = uuid4().hex
    path = scoped_path(directory, identifier + ".py")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
        handle.write(code)
    record = {"proposal_id": identifier, "run_id": run_id, "purpose": purpose, "sha256": hashlib.sha256(code.encode()).hexdigest(), "created_at": timestamp(), "status": "awaiting_review"}
    write_json(directory / (identifier + ".json"), record, exclusive=True)
    return record


def read_proposal(context: SessionContext, identifier: str) -> tuple[dict, Path, str]:
    """Load a saved proposal, refusing it if the bytes changed after review."""
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise AgentError("INVALID_PROPOSAL", "Select a saved proposal from this session.")
    directory = scoped_path(context.directory, "generated", directory=True)
    record = read_json(scoped_path(directory, identifier + ".json"))
    path = scoped_path(directory, identifier + ".py")
    with path.open("rb") as handle:
        data = handle.read(MAX_SCRIPT_BYTES + 1)
    if len(data) > MAX_SCRIPT_BYTES or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise AgentError("PROPOSAL_CHANGED", "The script changed after it was saved. Request a new proposal and review it again.")
    context.run(record["run_id"])
    return record, path, data.decode("utf-8")


def sandbox_command(executable: str, name: str, image: str, run: Path, script: Path) -> list[str]:
    """Build the docker create argument list for one approved script."""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise AgentError("INVALID_IMAGE", "Use the immutable sha256 image ID of a separately prepared analysis sandbox.")
    if os.getuid() == 0:
        raise AgentError("ROOT_NOT_ALLOWED", "Run GridLens as a normal user to execute a reviewed script.")
    if any("," in str(path) for path in (run, script)):
        raise AgentError("UNSUPPORTED_PATH", "Docker bind mount paths cannot contain commas.")
    return [executable, "--host", DOCKER_HOST, "create", "--name", name, "--pull=never", "--runtime", "runc",
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--user", f"{os.getuid()}:{os.getgid()}", "--cpus", "2", "--memory", "1g", "--memory-swap", "1g",
            "--pids-limit", "64", "--ulimit", "nofile=256:256", "--ulimit", "fsize=16777216:16777216", "--ulimit", "cpu=120:120",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777", "--tmpfs", "/output:rw,noexec,nosuid,size=32m,mode=1777",
            "--mount", f"type=bind,src={run},dst=/run-data,readonly", "--mount", f"type=bind,src={script},dst=/analysis.py,readonly",
            "--workdir", "/output", "--env", "NVIDIA_VISIBLE_DEVICES=void", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONUNBUFFERED=1", "--entrypoint", "python", image, "-I", "-B", "/analysis.py"]


def execute_proposal(context: SessionContext, identifier: str, approved_hash: str, image: str, *, cancelled=None, timeout: float = 120) -> dict:
    """Called only by the review dialog, never exposed as an MCP tool."""
    record, script, code = read_proposal(context, identifier)
    if approved_hash != record["sha256"]:
        raise AgentError("APPROVAL_REQUIRED", "Review and approve this exact script before execution.")
    executable = shutil.which("docker")
    if executable is None:
        raise AgentError("DOCKER_UNAVAILABLE", "Install and configure Docker yourself before running a reviewed script.")
    name = "gridlens-analysis-" + uuid4().hex
    run = context.run(record["run_id"])
    # Validate the image ID and refuse to run as root before anything is written to the session folder.
    # The command used later is rebuilt against the snapshot, so this call is a preflight check only.
    sandbox_command(executable, name, image, run, script)
    environment = minimal_environment()
    _require_sandbox_image(executable, image, environment)
    cancelled = cancelled or threading.Event()
    execution = scoped_path(context.directory, Path("generated/executions") / uuid4().hex, directory=True)
    execution.mkdir(parents=True, mode=0o700)
    # Execute the reviewed bytes, even if the original proposal is subsequently edited.
    snapshot = execution / "script.py"
    with os.fdopen(os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
        handle.write(code)
    command = sandbox_command(executable, name, image, run, snapshot)
    result = {"proposal_id": identifier, "script_sha256": approved_hash, "image": image, "approved_at": timestamp(), "command": command, "status": "running", "exit_code": None, "untrusted": True}
    write_json(execution / "result.json", result)
    append_event(context.directory, "script_executions.jsonl", {"phase": "approved", **result})
    process = None
    output = bytearray()
    try:
        created = subprocess.run(command, capture_output=True, timeout=CREATE_TIMEOUT_SECONDS, env=environment)
        if created.returncode:
            raise AgentError("SANDBOX_FAILED", created.stderr.decode(errors="replace")[:2000])
        if cancelled.is_set():
            raise AgentError("CANCELLED", "Script execution cancelled.")
        process = subprocess.Popen([executable, "--host", DOCKER_HOST, "start", "--attach", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
        deadline = time.monotonic() + timeout
        _stream_bounded_output(process, output, cancelled, deadline)
        result["exit_code"] = process.wait(timeout=2)
        result["status"] = "completed" if result["exit_code"] == 0 else "failed"
    except (AgentError, OSError, subprocess.SubprocessError) as exc:
        result.update(status="failed", error=exc.code if isinstance(exc, AgentError) else "SANDBOX_FAILED", detail=str(exc)[:2000])
    finally:
        if not _remove_container(executable, name, environment):
            result["cleanup_warning"] = "Check Docker for the recorded GridLens container name."
        if process:
            terminate_process(process)
            process.stdout.close()
        result.update(ended_at=timestamp(), stdout_sha256=hashlib.sha256(output).hexdigest(), stdout_bytes=len(output), output_excerpt=output.decode(errors="replace")[:16000], execution_id=execution.name)
        with os.fdopen(os.open(execution / "output.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
            handle.write(output)
        write_json(execution / "result.json", result)
        append_event(context.directory, "script_executions.jsonl", {"phase": "completed", **result})
    return result
