from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from gridlens.agent.policy import AgentError, local_endpoint


MAX_JSON_BYTES = 2 * 1024 * 1024


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def scoped_path(root: Path, relative: str | Path, *, directory: bool = False) -> Path:
    """Reject traversal and symlinks, including links to another selected run."""
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise AgentError("PATH_OUTSIDE_SESSION", "Use a selected run ID and a supported artifact kind.")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise AgentError("PATH_OUTSIDE_SESSION", "Symlinked agent artifacts are not supported.")
    if not path.resolve().is_relative_to(root.resolve()):
        raise AgentError("PATH_OUTSIDE_SESSION", "The artifact is outside the selected run.")
    if path.exists():
        mode = path.stat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            raise AgentError("INVALID_ARTIFACT", "Use a regular file or the expected artifact directory.")
    return path


def read_json(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError) as exc:
        raise AgentError("INVALID_ARTIFACT", "A JSON artifact is missing, malformed, or too large; rebuild it in GridLens.") from exc


def write_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_EXCL if exclusive else os.O_TRUNC)
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def append_event(directory: Path, name: str, value: dict) -> None:
    path = scoped_path(directory, name)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": timestamp(), **value}, ensure_ascii=False, allow_nan=False) + "\n")


def export_session(directory: Path, destination: Path) -> None:
    """Explicit audit export, excluding the CLI profile and internal runtime history."""
    names = ("context.json", "manifest.json", "transcript.jsonl", "runtime_events.jsonl", "tool_calls.jsonl", "usage.json", "status.json", "script_executions.jsonl")
    paths = [scoped_path(directory, name) for name in names]
    generated = scoped_path(directory, "generated", directory=True)
    if generated.exists():
        paths.extend(scoped_path(directory, path.relative_to(directory)) for path in generated.rglob("*") if path.is_file() or path.is_symlink())
    paths = [path for path in paths if path.exists()]
    if len(paths) > 1000 or sum(path.stat().st_size for path in paths) > 64 * 1024 * 1024:
        raise AgentError("EXPORT_LIMIT", "This session exceeds the 64 MiB / 1,000-file export limit. Review its folder directly.")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".gridlens-audit-") as temporary:
        archive_path = Path(temporary) / "audit.zip"
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, str(path.relative_to(directory)))
        # Copy through a new inode; never follow an existing destination symlink.
        os.chmod(archive_path, 0o600)
        os.replace(archive_path, destination)


@dataclass(frozen=True)
class SessionContext:
    project_root: Path
    run_ids: tuple[str, ...]
    model: str
    endpoint: str
    directory: Path
    session_id: str
    runtime: str = "hermes"

    def run(self, run_id: str) -> Path:
        if run_id not in self.run_ids or not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id) or run_id in (".", ".."):
            raise AgentError("RUN_NOT_SELECTED", "Select this run in the Agent tab and start a new session.")
        path = scoped_path(self.project_root, Path("runs") / run_id, directory=True)
        status = read_json(scoped_path(path, "status.json"))
        if status.get("status") != "completed":
            raise AgentError("RUN_NOT_COMPLETED", "Select a completed GridPACK run.")
        return path

    @classmethod
    def create(cls, project_root: Path, run_ids: tuple[str, ...], model: str, endpoint: str) -> "SessionContext":
        root = project_root.expanduser().resolve(strict=True)
        read_json(scoped_path(root, "project.json"))
        if not run_ids or len(run_ids) > 2 or len(set(run_ids)) != len(run_ids):
            raise AgentError("INVALID_SELECTION", "Select one completed run, or two runs for comparison.")
        if not model or len(model) > 256:
            raise AgentError("INVALID_MODEL", "Select an installed Ollama model.")
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:12]
        directory = scoped_path(root, Path("agent/sessions") / identifier, directory=True)
        context = cls(root, run_ids, model, local_endpoint(endpoint), directory, identifier)
        for run_id in run_ids:
            context.run(run_id)
        directory.mkdir(parents=True, mode=0o700)
        os.chmod(directory, 0o700)
        value = asdict(context)
        value.update(project_root=str(root), directory=str(directory))
        write_json(directory / "context.json", value, exclusive=True)
        context.set_status("ready")
        return context

    @classmethod
    def load(cls, path: Path) -> "SessionContext":
        if path.is_symlink() or not path.is_file():
            raise AgentError("INVALID_SESSION", "Start a new session from the Agent tab.")
        data = read_json(path)
        try:
            context = cls(
                Path(data["project_root"]), tuple(data["run_ids"]), data["model"], data["endpoint"],
                Path(data["directory"]), data["session_id"], data["runtime"],
            )
            if (
                context.runtime != "hermes" or not context.project_root.is_absolute()
                or context.project_root != context.project_root.resolve()
                or not re.fullmatch(r"[A-Za-z0-9_]+", context.session_id)
                or context.directory != scoped_path(context.project_root, Path("agent/sessions") / context.session_id, directory=True)
                or path.absolute() != context.directory / "context.json"
                or not 1 <= len(context.run_ids) <= 2
                or context.endpoint != local_endpoint(context.endpoint)
            ):
                raise ValueError
            read_json(scoped_path(context.project_root, "project.json"))
            for run_id in context.run_ids:
                context.run(run_id)
            return context
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentError("INVALID_SESSION", "The session context is invalid; start a new session.") from exc

    def set_status(self, status: str, detail: str = "") -> None:
        write_json(scoped_path(self.directory, "status.json"), {"status": status, "detail": detail, "updated_at": timestamp()})

    def message(self, role: str, text: str) -> None:
        append_event(self.directory, "transcript.jsonl", {"role": role, "text": text})
