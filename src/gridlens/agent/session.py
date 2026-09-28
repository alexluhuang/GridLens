"""The session record, project and run lookup, and the audit files.

A session is one conversation. `SessionContext` is written once, at creation, and names the GridLens
projects folder, the model, and the route. The route is the security decision made here: it is fixed
before any project text can reach a runtime. The project open in GridLens and the runs selected there are
the session's focus, which the user may change between turns; `focus.json` records the latest one.

A session does not limit which projects or runs the tools may use. The agent can create projects, start
runs, and read every file of a GridLens project, so tools name a project and a run, and `find_project`
and `resolve_run` turn those names into folders. `scoped_path` guarantees that a resolved path stays
inside the folder it was resolved against and never follows a symlink out of it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
from gridlens.agent.providers import DEFAULT_PROVIDER, PROVIDER_IDS, route_for


MAX_JSON_BYTES = 2 * 1024 * 1024
EXPORT_MAX_BYTES = 2 * 1024 * 1024 * 1024
EXPORT_MAX_FILES = 10_000
PROJECT_FILE = "project.json"
# Sessions live in a hidden folder of the projects folder, which is never mistaken for a project because it
# has no project.json, so one conversation can move between projects. Sessions written before that lived
# inside the project open when they started, and are still listed and opened from there.
WORKSPACE_SESSIONS = Path(".gridlens-agent/sessions")
PROJECT_SESSIONS = Path("agent/sessions")
FOCUS_FILE = "focus.json"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")


def safe_utf8(value: object) -> object:
    """Replace invalid Unicode in nested audit values before writing JSON for later tool use."""
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {str(safe_utf8(key)): safe_utf8(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_utf8(item) for item in value]
    return value


def timestamp() -> str:
    """Return the current UTC time as an ISO-8601 string with millisecond precision."""
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
    """Read a bounded JSON object, or refuse when it is missing, malformed, or oversized."""
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
    """Write JSON at mode 0600, through a descriptor that never follows a symlink."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_EXCL if exclusive else os.O_TRUNC)
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as handle:
        json.dump(safe_utf8(value), handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def append_event(directory: Path, name: str, value: dict) -> None:
    """Append one timestamped JSON line to a session audit file."""
    path = scoped_path(directory, name)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_utf8({"timestamp": timestamp(), **value}), ensure_ascii=False, allow_nan=False) + "\n")


def export_session(directory: Path, destination: Path) -> None:
    """Explicit audit export, excluding the CLI profile and internal runtime history.

    The export holds the session record, the audit, generated scripts, and the complete tool results in
    results/. A session larger than the export limit has to be reviewed in its folder.
    """
    names = ("context.json", FOCUS_FILE, "manifest.json", "transcript.jsonl", "runtime_events.jsonl", "tool_calls.jsonl", "usage.json", "status.json", "script_executions.jsonl")
    paths = [scoped_path(directory, name) for name in names]
    for folder in ("generated", "results"):
        tree = scoped_path(directory, folder, directory=True)
        if tree.exists():
            paths.extend(scoped_path(directory, path.relative_to(directory)) for path in tree.rglob("*") if path.is_file() or path.is_symlink())
    paths = [path for path in paths if path.exists()]
    if len(paths) > EXPORT_MAX_FILES or sum(path.stat().st_size for path in paths) > EXPORT_MAX_BYTES:
        raise AgentError("EXPORT_LIMIT", "This session exceeds the 2 GiB / 10,000-file export limit. Review its folder directly.")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".gridlens-audit-") as temporary:
        archive_path = Path(temporary) / "audit.zip"
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, str(path.relative_to(directory)))
        # Copy through a new inode; never follow an existing destination symlink.
        os.chmod(archive_path, 0o600)
        os.replace(archive_path, destination)


def default_projects_dir() -> Path:
    """Return the projects folder named in the user's GridLens settings."""
    from gridlens.core.app_settings import AppSettings

    return AppSettings.load().default_projects_dir.expanduser()


def project_folders(projects_dir: Path) -> list[Path]:
    """Return the GridLens project folders directly inside projects_dir, sorted by folder name."""
    if not projects_dir.is_dir():
        return []
    return sorted(
        path for path in projects_dir.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / PROJECT_FILE).is_file()
    )


def find_project(name: str, projects_dir: Path) -> Path:
    """Resolve a project folder path, a folder name, or the name recorded in project.json to its folder.

    A relative name is looked up inside projects_dir first as a folder name, then by the project name
    each project.json records, so both "GridPACK_Test_Project" and "GridPACK Test Project" work.
    """
    candidate = Path(name).expanduser()
    if not candidate.is_absolute():
        candidate = projects_dir / name
    if (candidate / PROJECT_FILE).is_file():
        return candidate.resolve()
    for folder in project_folders(projects_dir):
        try:
            if read_json(folder / PROJECT_FILE).get("name") == name:
                return folder.resolve()
        except AgentError:
            continue
    raise AgentError("PROJECT_NOT_FOUND", f"No GridLens project matches '{name[:200]}'. Use list_projects, or pass the project folder path.")


def resolve_run(project_root: Path, run_id: str, *, completed: bool = True) -> Path:
    """Return the folder of one run of a project.

    Refuses an ID that is not a plain folder name, a run that does not exist, and, when completed is
    True, a run whose status.json does not say it completed.
    """
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id) or run_id in (".", ".."):
        raise AgentError("INVALID_RUN_ID", "Use a run ID from get_project, such as 2026-07-28_14-46-26.")
    path = scoped_path(project_root, Path("runs") / run_id, directory=True)
    if not path.is_dir():
        raise AgentError("RUN_NOT_FOUND", f"The project has no run named {run_id}. Use get_project to list its runs.")
    if completed:
        status_path = scoped_path(path, "status.json")
        if not status_path.is_file() or read_json(status_path).get("status") != "completed":
            raise AgentError("RUN_NOT_COMPLETED", "This run has not completed. Check it with get_status, or choose a completed run.")
    return path


def saved_sessions(projects_dir: Path, project_root: Path | None = None, *, limit: int = 100) -> list[Path]:
    """Return the newest session folders of the projects folder, and the older ones kept inside project_root.

    Session folder names begin with their UTC creation time, so sorting by name puts the newest first.
    """
    folders = []
    for base, sessions in ((projects_dir, WORKSPACE_SESSIONS), (project_root, PROJECT_SESSIONS)):
        if base is None:
            continue
        root = scoped_path(base, sessions, directory=True)
        if root.is_dir():
            folders.extend(path for path in root.iterdir() if path.is_dir() and not path.is_symlink())
    return sorted(folders, key=lambda path: path.name, reverse=True)[:limit]


def session_title(directory: Path, limit: int = 80) -> str:
    """Return the session's creation time and its first question, for a list of saved conversations."""
    stamp = directory.name.split("_", 1)[0]
    try:
        label = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        label = directory.name
    try:
        with scoped_path(directory, "transcript.jsonl").open("rb") as handle:
            first = json.loads(handle.readline(64 * 1024) or b"{}")
        question = " ".join(str(first.get("text", "")).split()) if first.get("role") == "user" else ""
    except (AgentError, OSError, ValueError, AttributeError):
        question = ""
    if len(question) > limit:
        question = question[:limit].rstrip() + "…"
    return f"{label}  ·  {question}" if question else label


def _validated_focus(project_root: Path | None, run_ids: tuple[str, ...]) -> tuple[Path | None, tuple[str, ...]]:
    """Resolve a focus project and check its selected runs, or refuse the selection."""
    root = None
    if project_root is not None:
        root = project_root.expanduser().resolve(strict=True)
        read_json(scoped_path(root, PROJECT_FILE))
    run_ids = tuple(run_ids)
    if len(run_ids) > 2 or len(set(run_ids)) != len(run_ids) or (run_ids and root is None):
        raise AgentError("INVALID_SELECTION", "Select at most two different completed runs of the open project.")
    for run_id in run_ids:
        resolve_run(root, run_id)
    return root, run_ids


def _surviving_focus(project_root: Path | None, run_ids: tuple[str, ...]) -> tuple[Path | None, tuple[str, ...]]:
    """Return the part of a saved focus that still exists, so a deleted project or run leaves a session readable."""
    try:
        root, _ = _validated_focus(project_root, ())
    except (AgentError, OSError):
        return None, ()
    if root != project_root:
        return None, ()
    surviving = []
    for run_id in dict.fromkeys(run_ids):
        try:
            resolve_run(root, run_id)
            surviving.append(run_id)
        except AgentError:
            continue
    return root, tuple(surviving)


@dataclass(frozen=True)
class SessionContext:
    """The record of one conversation. context.json is written once and never amended.

    Creating a context is the moment the route is decided, before any project text can reach a runtime.
    Changing the model or the runtime means starting a new session. project_root is the project open in
    GridLens, or None, and run_ids are the runs selected there. They are the conversation's focus, not a
    limit: tools may name any project and any run, and `refocus` moves the focus to another project or
    other runs between turns, so one conversation can create, run, and compare several projects.
    """

    project_root: Path | None
    run_ids: tuple[str, ...]
    model: str
    endpoint: str
    directory: Path
    session_id: str
    runtime: str = DEFAULT_PROVIDER
    route: str = "loopback_only"
    # True only when the user confirmed, for this session, that a hosted runtime may receive project data.
    remote_acknowledged: bool = False
    # The folder GridLens lists and creates projects in. None only for contexts built directly in code.
    projects_dir: Path | None = None

    @property
    def projects_folder(self) -> Path:
        """Return the folder GridLens lists and creates projects in."""
        if self.projects_dir is not None:
            return self.projects_dir
        if self.project_root is not None:
            return self.project_root.parent
        raise AgentError("NO_PROJECTS_FOLDER", "Start a new session; this one records no projects folder.")

    def refocus(self, project_root: Path | None, run_ids: tuple[str, ...]) -> "SessionContext":
        """Record a new project and runs in focus for the next turn, and return the context that has them.

        The focus is written to focus.json, which `load` applies over the fields context.json began with,
        so the tool server of the next turn sees it. The route, runtime, and model do not change.
        """
        root, run_ids = _validated_focus(project_root, run_ids)
        if (root, run_ids) == (self.project_root, self.run_ids):
            return self
        write_json(scoped_path(self.directory, FOCUS_FILE), {"project_root": str(root) if root else None, "run_ids": list(run_ids), "updated_at": timestamp()})
        return replace(self, project_root=root, run_ids=run_ids)

    def run(self, run_id: str, *, completed: bool = True) -> Path:
        """Resolve a run of the session's project to its folder, or refuse the request."""
        if self.project_root is None:
            raise AgentError("NO_PROJECT", "Name a project (list_projects shows them) or create one with create_project.")
        return resolve_run(self.project_root, run_id, completed=completed)

    @classmethod
    def create(
        cls, project_root: Path | None, run_ids: tuple[str, ...], model: str, endpoint: str,
        *, runtime: str = DEFAULT_PROVIDER, remote_acknowledged: bool = False, projects_dir: Path | None = None,
    ) -> "SessionContext":
        """Create the session folder in the projects folder and write its immutable record.

        project_root may be None, for a conversation started before any project is open, and the selected
        runs must then be empty.
        """
        projects = (projects_dir or default_projects_dir()).expanduser().resolve()
        root, run_ids = _validated_focus(project_root, run_ids)
        if not model or len(model) > 256:
            raise AgentError("INVALID_MODEL", "Select a model for the chosen runtime.")
        # The route is decided here, before any user text or project name reaches a runtime process.
        route = route_for(runtime)
        if route == "remote":
            if not remote_acknowledged:
                raise AgentError("REMOTE_NOT_ACKNOWLEDGED", "Confirm the remote-data acknowledgement in the Agent tab before starting a hosted session.")
            endpoint = ""
        else:
            endpoint = local_endpoint(endpoint)
            remote_acknowledged = False
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:12]
        projects.mkdir(parents=True, exist_ok=True)
        directory = scoped_path(projects, WORKSPACE_SESSIONS / identifier, directory=True)
        context = cls(root, run_ids, model, endpoint, directory, identifier, runtime, route, remote_acknowledged, projects)
        directory.mkdir(parents=True, mode=0o700)
        os.chmod(directory, 0o700)
        value = asdict(context)
        value.update(project_root=str(root) if root else None, directory=str(directory), projects_dir=str(projects))
        write_json(directory / "context.json", value, exclusive=True)
        context.set_status("ready")
        return context

    @classmethod
    def load(cls, path: Path) -> "SessionContext":
        """Load a context file and the latest focus, re-validating every field before trusting it.

        A record written before sessions named their projects folder uses the project's parent folder. A
        session folder is either in the projects folder or, for an older session, inside the project it
        began with.
        """
        if path.is_symlink() or not path.is_file():
            raise AgentError("INVALID_SESSION", "Start a new session from the Agent tab.")
        data = read_json(path)
        try:
            root = Path(data["project_root"]) if data.get("project_root") else None
            projects = Path(data["projects_dir"]) if data.get("projects_dir") else (root.parent if root else None)
            context = cls(
                root, tuple(data["run_ids"]), data["model"], data["endpoint"],
                Path(data["directory"]), data["session_id"], data["runtime"],
                str(data.get("route", "loopback_only")), bool(data.get("remote_acknowledged", False)), projects,
            )
            remote = context.route == "remote"
            if (
                context.runtime not in PROVIDER_IDS
                or context.route != route_for(context.runtime)
                or (remote and (not context.remote_acknowledged or context.endpoint))
                or (not remote and (context.remote_acknowledged or context.endpoint != local_endpoint(context.endpoint)))
                or projects is None or not projects.is_absolute()
                or (root is not None and (not root.is_absolute() or root != root.resolve()))
                or not re.fullmatch(r"[A-Za-z0-9_]+", context.session_id)
                or path.absolute() != context.directory / "context.json"
                or len(context.run_ids) > 2 or (context.run_ids and root is None)
            ):
                raise ValueError
            locations = [scoped_path(projects, WORKSPACE_SESSIONS / context.session_id, directory=True)]
            if root is not None:
                locations.append(scoped_path(root, PROJECT_SESSIONS / context.session_id, directory=True))
            if context.directory not in locations:
                raise ValueError
            run_ids = context.run_ids
            focus_path = scoped_path(context.directory, FOCUS_FILE)
            if focus_path.exists():
                focus = read_json(focus_path)
                root = Path(focus["project_root"]) if focus.get("project_root") else None
                run_ids = tuple(str(run_id) for run_id in focus["run_ids"])
                if (root is not None and not root.is_absolute()) or len(run_ids) > 2 or (run_ids and root is None):
                    raise ValueError
            root, run_ids = _surviving_focus(root, run_ids)
            return replace(context, project_root=root, run_ids=run_ids)
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentError("INVALID_SESSION", "The session context is invalid; start a new session.") from exc

    def set_status(self, status: str, detail: str = "") -> None:
        """Record the session state that the GUI and the audit read."""
        write_json(scoped_path(self.directory, "status.json"), {"status": status, "detail": detail, "updated_at": timestamp()})

    def message(self, role: str, text: str) -> None:
        """Append one conversation message to the transcript."""
        append_event(self.directory, "transcript.jsonl", {"role": role, "text": text})
