"""Tools that operate GridLens: projects, run configuration, GridPACK runs, and analysis builds.

These tools do what the Project, Configuration, Run, Branch Analysis, and Transformer Analysis tabs do,
through the same functions those tabs call, so a project the agent sets up is one the GUI can open and a
run it starts is recorded exactly like a run started from the Run tab.

A GridPACK run and an analysis build take minutes, so `start_run` and `run_analysis` start a background
job (see `gridlens.agent.jobs`) and return its ID at once. `get_status` reports a job's or a run's state
and can wait for it to end; the analysis tools read a run's results once its analysis job has completed.
`stop` ends a job or a run.

A change that replaces or ends something the user already has, an input file, the project's XML, or a
running job, waits for the user. Over MCP, the first call returns a preview and changes nothing, and the
change is made only when the same call comes back with confirm=True after the user has sent another
message. A model cannot preview and confirm in one turn, so it has to stop and ask.

Run settings the agent does not give, such as the Docker image and the MPI process count, come from the
settings the Run tab saved last. Input files are imported from any absolute path; everything else these
tools write stays inside the project folder.
"""
from __future__ import annotations

from dataclasses import asdict, fields, replace
import difflib
import hashlib
import json
from pathlib import Path
from typing import Literal

from gridlens.agent import jobs
from gridlens.agent.policy import AgentError
from gridlens.agent.session import PROJECT_FILE, RUN_ID_PATTERN, project_folders, read_json, resolve_run, scoped_path, timestamp, write_json
from gridlens.agent.tool_base import ToolBase, tool
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.parser_models import PARSER_VERSION
from gridlens.core.app_settings import AppSettings
from gridlens.core.project import Project, ProjectData
from gridlens.core.validation import validate_existing_files
from gridlens.gui.configuration_view_models import (
    CONTINGENCY_OUTPUT_FORMAT_OPTIONS,
    CONTINGENCY_RATING_OPTIONS,
    DEFAULT_XML_FILE_NAME,
    INIT_START_OPTIONS,
    NETWORK_CONFIGURATION_TAG_OPTIONS,
    InputConfigurationValues,
    default_input_configuration_values,
    load_input_configuration_values,
    project_network_file_names,
    save_input_configuration,
    validated_input_configuration,
)
from gridlens.gui.project_view_models import ProjectFormValues, default_project_folder, prepare_project_save
from gridlens.gui.run_view_models import RunFormValues, validate_run_form_values
from gridlens.runner import docker_probe
from gridlens.runner.gridpack_runner import gridpack_container_name, terminate_gridpack_run
from gridlens.runner.run_progress import GridpackProgressParser


GRIDLENS_TOOL_NAMES = (
    "list_projects", "get_project", "get_status", "create_project", "add_project_inputs", "get_run_configuration",
    "configure_run", "start_run", "run_analysis", "stop",
)
GRIDLENS_WRITE_TOOL_NAMES = frozenset({"create_project", "add_project_inputs", "configure_run", "start_run", "run_analysis", "stop"})
# Tools that can replace or end something the user already had: an input file, the XML, or a running job.
GRIDLENS_DESTRUCTIVE_TOOL_NAMES = frozenset({"add_project_inputs", "configure_run", "stop"})
# Changes previewed in this session and waiting for the user, in the session folder.
PENDING_CHANGES = "pending_changes.json"
MAX_PENDING_CHANGES = 50
# get_status waits less than the runtime's tool-call timeout, so a long wait returns before the call is abandoned.
MAX_WAIT_SECONDS = 1500
CONFIGURATION_CHOICES = {
    "contingency_rating": CONTINGENCY_RATING_OPTIONS,
    "contingency_output_format": CONTINGENCY_OUTPUT_FORMAT_OPTIONS,
    "init_start": INIT_START_OPTIONS,
    "network_configuration_tag": NETWORK_CONFIGURATION_TAG_OPTIONS,
}
AnalysisKind = Literal["branch", "transformer", "both"]


def _absolute_files(paths: list[str]) -> list[Path]:
    """Return input file paths as existing files, refusing relative paths, whose base would be ambiguous."""
    for path in paths or []:
        if not Path(str(path)).expanduser().is_absolute():
            raise AgentError("ABSOLUTE_PATH_REQUIRED", f"Give input files as absolute paths, not '{str(path)[:200]}'.")
    return validate_existing_files(list(paths or []))


def _project_record(root: Path) -> tuple[Project, ProjectData]:
    """Open the project in root, trusting the folder it is in over the root_dir its project.json recorded."""
    try:
        data = ProjectData.from_dict(read_json(scoped_path(root, PROJECT_FILE)))
    except (KeyError, TypeError) as exc:
        raise AgentError("INVALID_PROJECT", "This project's project.json is incomplete. Open and save the project in the Project tab.") from exc
    return Project(data.name, root), data


def _current_configuration(root: Path, data: ProjectData) -> InputConfigurationValues:
    """Return the project's saved XML settings, or the Configuration tab's defaults when it has no XML yet."""
    network = (project_network_file_names(data) or [""])[0]
    if data.xml_file_name:
        xml = scoped_path(root, Path("original_inputs") / data.xml_file_name)
        if xml.is_file():
            return load_input_configuration_values(xml, network, data.xml_file_name, data.name)
    return default_input_configuration_values(network, DEFAULT_XML_FILE_NAME, data.name)


def _coerce(name: str, value: object, default: object) -> object:
    """Convert a setting to its form type: booleans from true/false, and everything else to text."""
    if not isinstance(default, bool):
        return str(value)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise AgentError("INVALID_SETTING", f"{name} must be true or false.")


def _sha256(path: Path) -> str:
    """Return a file's SHA-256, as a project records its inputs."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _user_turns(directory: Path) -> int:
    """Count the user's messages in a session transcript; a change previewed in one turn is confirmed in a later one."""
    path = scoped_path(directory, "transcript.jsonl")
    if not path.exists():
        return 0
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                count += json.loads(line).get("role") == "user"
            except (ValueError, AttributeError):
                continue
    return count


def _run_settings(settings: AppSettings) -> dict:
    """Return the Run tab's saved settings that start_run uses when the agent gives none."""
    return {
        "image": settings.default_gridpack_image, "executable": settings.default_executable,
        "mpi_processes": settings.default_mpi_processes, "pull_policy": settings.docker_pull_policy,
        "network_disabled": settings.docker_network_mode == "none", "use_platform_flag": settings.use_platform_flag,
        "use_host_user": settings.use_host_user, "memory_limit": settings.memory_limit, "extra_docker_args": settings.extra_docker_args,
    }


class GridLensTools(ToolBase):
    """The GridLens operation tools, bound to one session."""

    def _held(self, name: str, root: Path, change: object, state: object, preview: dict, confirm: bool) -> dict | None:
        """Hold a change until the user agrees to it: return the preview to send instead, or None to make it.

        A model can call a tool twice in one turn, so confirm=True counts only for a change previewed in an
        earlier turn, that is, when the user has sent a message since. state fingerprints what the change
        replaces, so a preview goes stale, and is shown again, if the project changed before the user agreed.
        """
        if not self.confirm_changes:
            return None
        turn = _user_turns(self.context.directory)
        key = hashlib.sha256(json.dumps([name, str(root), change, state], sort_keys=True, default=str).encode()).hexdigest()[:16]
        path = scoped_path(self.context.directory, PENDING_CHANGES)
        pending = read_json(path) if path.exists() else {}
        record = pending.get(key)
        if confirm and record and record["turn"] < turn:
            del pending[key]
            write_json(path, pending)
            return None
        if confirm and record:
            raise AgentError("CONFIRMATION_REQUIRED", "Nothing was changed: the user has not replied since this change was previewed. End your turn, show the user the change, and ask them to confirm it.")
        pending.setdefault(key, {"tool": name, "turn": turn, "previewed_at": timestamp()})
        write_json(path, dict(list(pending.items())[-MAX_PENDING_CHANGES:]))
        ignored = " confirm=True was ignored because the user has not seen this change." if confirm else ""
        return {
            **preview, "confirmation_required": True, "change_id": key,
            "next_step": f"Nothing was changed.{ignored} Show the user exactly this change, ask whether to make it, and end your turn. If they agree in their next message, call {name} again with the same arguments and confirm=True.",
        }

    @tool
    def list_projects(self, offset: int = 0, limit: int = 100) -> dict:
        """List the GridLens projects in the projects folder, and the project open in the GUI, with their run counts."""
        folders = project_folders(self.context.projects_folder)
        if self.context.project_root is not None and self.context.project_root not in folders:
            folders.insert(0, self.context.project_root)
        rows = []
        for folder in folders:
            data = read_json(folder / PROJECT_FILE)
            runs = folder / "runs"
            names = sorted(path.name for path in runs.iterdir() if path.is_dir()) if runs.is_dir() else []
            rows.append({
                "name": data.get("name", folder.name), "folder": str(folder), "open_in_gui": folder == self.context.project_root,
                "xml_file_name": data.get("xml_file_name", ""), "input_file_count": len(data.get("input_files", [])),
                "run_count": len(names), "latest_run": names[-1] if names else None, "updated_at": data.get("updated_at"),
            })
        return {"rows": rows, "projects_folder": str(self.context.projects_folder)}

    @tool
    def get_project(self, project: str = "", offset: int = 0, limit: int = 50) -> dict:
        """Show a project's name, folder, XML file, and input files with their sizes and SHA-256 hashes, and list its runs newest first with status, whether each has a current analysis cache, its cached tables, and whether it has a drill-down index."""
        root = self._project(project)
        try:
            _, data = _project_record(root)
            record = {"name": data.name, "xml_file_name": data.xml_file_name, "created_at": data.created_at, "updated_at": data.updated_at, "input_files": [asdict(item) for item in data.input_files]}
        except AgentError as exc:
            # The runs are still worth listing when project.json lacks the fields the Project tab saves.
            self.warnings.append(str(exc))
            saved = read_json(scoped_path(root, PROJECT_FILE))
            record = {"name": saved.get("name", root.name), "xml_file_name": saved.get("xml_file_name", ""), "created_at": saved.get("created_at"), "updated_at": saved.get("updated_at"), "input_files": []}
        runs = scoped_path(root, "runs", directory=True)
        rows = []
        for path in sorted(runs.iterdir(), reverse=True) if runs.is_dir() else []:
            if path.is_symlink() or not path.is_dir() or not RUN_ID_PATTERN.fullmatch(path.name):
                continue
            status = self._json(path, "status.json").get("status") if (path / "status.json").is_file() else "not started"
            manifest = self._json(path, "reports/interactive_analysis_manifest.json") if (path / "reports/interactive_analysis_manifest.json").is_file() else None
            tables = path / "reports/interactive_tables"
            rows.append({
                "run_id": path.name, "status": status, "path": str(path),
                "selected_in_gui": root == self.context.project_root and path.name in self.context.run_ids,
                "interactive_analysis_available": manifest is not None,
                # A cache written by an older GridLens is refused by the analysis tools until it is rebuilt.
                "analysis_current": manifest is not None and (manifest.get("dataset_version"), manifest.get("parser_version")) == (ANALYSIS_DATASET_VERSION, PARSER_VERSION),
                "cached_tables": sorted(item.stem for item in tables.glob("*.csv")) if tables.is_dir() else [],
                "event_index_available": (path / "reports/event_index/manifest.json").is_file(),
            })
        return {"rows": rows, "folder": str(root), "run_count": len(rows), **record}

    @tool
    def create_project(self, name: str, input_files: list[str], xml_file_name: str = "", folder: str = "") -> dict:
        """Create a GridLens project and copy its input files (absolute paths: RAW case, XML, contingency and monitor lists) into it. folder defaults to the projects folder."""
        target = Path(folder).expanduser() if folder.strip() else default_project_folder(self.context.projects_folder, name)
        if (target / PROJECT_FILE).exists():
            raise AgentError("PROJECT_EXISTS", f"A project already exists in {target}. Use add_project_inputs to change it.")
        files = _absolute_files(input_files)
        prepared = prepare_project_save(ProjectFormValues(name, target, files, xml_file_name))
        data = prepared.project.save(prepared.input_files, prepared.xml_file_name)
        return {
            "rows": [asdict(record) for record in data.input_files], "name": data.name, "folder": str(prepared.project.root_dir),
            "xml_file_name": data.xml_file_name, "next_step": "Use configure_run to write the GridPACK XML, then start_run.",
        }

    @tool
    def add_project_inputs(self, input_files: list[str], project: str = "", xml_file_name: str = "", confirm: bool = False) -> dict:
        """Copy more input files (absolute paths) into a project. A file with the same name as an existing input replaces it. Replacing an input with different content, or switching the project's XML with xml_file_name, first returns a preview and changes nothing: show it to the user, and call again with confirm=True only after they agree in a later message."""
        root = self._project(project)
        project_record, data = _project_record(root)
        files = _absolute_files(input_files)
        current = {record.file_name: record for record in data.input_files}
        digests = {path.name: _sha256(path) for path in files}
        replaced = [name for name, digest in digests.items() if name in current and current[name].sha256 != digest]
        switched = bool(xml_file_name) and bool(data.xml_file_name) and xml_file_name != data.xml_file_name
        if replaced or switched:
            rows = [
                {"file": path.name, "action": "replace" if path.name in replaced else "unchanged" if path.name in current else "add", "source": str(path), "sha256": digests[path.name], "current_sha256": getattr(current.get(path.name), "sha256", None)}
                for path in files
            ]
            if switched:
                rows.append({"file": xml_file_name, "action": f"use as the project's XML instead of {data.xml_file_name}"})
            state = [sorted((name, record.sha256) for name, record in current.items()), data.xml_file_name]
            held = self._held("add_project_inputs", root, {"files": sorted(digests.items()), "xml_file_name": xml_file_name}, state, {"rows": rows}, confirm)
            if held is not None:
                return held
        names = {path.name for path in files}
        kept = [Path(record.stored_path) for record in data.input_files if record.file_name not in names]
        saved = project_record.save(kept + files, xml_file_name or data.xml_file_name)
        return {"rows": [asdict(record) for record in saved.input_files], "folder": str(root), "xml_file_name": saved.xml_file_name}

    @tool
    def get_run_configuration(self, project: str = "") -> dict:
        """Show every GridPACK XML setting of a project with its current value and allowed choices, plus the Docker run settings start_run uses by default."""
        root = self._project(project)
        _, data = _project_record(root)
        values = _current_configuration(root, data)
        rows = [{"setting": item.name, "value": getattr(values, item.name), "choices": list(CONFIGURATION_CHOICES.get(item.name, ()))} for item in fields(values)]
        return {
            "rows": rows, "xml_file_name": data.xml_file_name, "network_files": project_network_file_names(data),
            "input_files": [record.file_name for record in data.input_files], "run_settings": _run_settings(AppSettings.load()),
        }

    @tool
    def configure_run(self, settings: dict, project: str = "", confirm: bool = False) -> dict:
        """Change GridPACK XML settings by name, as listed by get_run_configuration (for example {"full_generator_n1": true, "max_voltage": "1.05"}), and save the XML into the project. Changing a project's existing XML first returns a preview, each setting's current and new value and the XML diff, and changes nothing: show it to the user, and call again with confirm=True only after they agree in a later message. A project with no XML yet gets one at once."""
        root = self._project(project)
        project_record, data = _project_record(root)
        current = _current_configuration(root, data)
        defaults = {item.name: getattr(current, item.name) for item in fields(current)}
        unknown = sorted(set(settings or {}) - set(defaults))
        if unknown:
            raise AgentError("UNKNOWN_SETTING", f"Unknown settings: {', '.join(unknown)[:500]}. Settings are: {', '.join(defaults)}.")
        changes = {name: _coerce(name, value, defaults[name]) for name, value in (settings or {}).items()}
        values = replace(current, **changes)
        if values.network_file_name not in {record.file_name for record in data.input_files}:
            raise AgentError("NETWORK_FILE_NOT_IN_PROJECT", "Set network_file_name to one of the project's input files, or add the case with add_project_inputs.")
        normalized, after = validated_input_configuration(data, values)
        existing = scoped_path(root, Path("original_inputs") / data.xml_file_name) if data.xml_file_name else None
        if existing is not None and existing.is_file():
            before = existing.read_text(encoding="utf-8")
            if after != before or normalized.xml_file_name != data.xml_file_name:
                rows = [{"setting": name, "current": getattr(current, name), "new": value} for name, value in changes.items()]
                diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"{data.xml_file_name} (saved)", f"{normalized.xml_file_name} (proposed)"))
                change = {name: str(value) for name, value in changes.items()}
                held = self._held("configure_run", root, change, hashlib.sha256(before.encode()).hexdigest(), {"rows": rows, "xml_file": str(existing), "xml_diff": diff[:20000]}, confirm)
                if held is not None:
                    return held
        saved = save_input_configuration(project_record, data, values)
        xml = scoped_path(root, Path("original_inputs") / saved.xml_file_name)
        return {"rows": [{"setting": name, "value": value} for name, value in changes.items()], "xml_file": str(xml), "xml_text": xml.read_text(encoding="utf-8")}

    @tool
    def start_run(self, project: str = "", image: str = "", executable: str = "", mpi_processes: int = 0, pull_policy: str = "", memory_limit: str = "", extra_docker_args: str = "", notes: str = "") -> dict:
        """Start a GridPACK run of a project in Docker as a background job and return its run_id and job_id. Blank settings use the Run tab's saved settings."""
        root = self._project(project)
        project_record, data = _project_record(root)
        if not data.xml_file_name:
            raise AgentError("NO_CONFIGURATION", "The project has no XML configuration. Save one with configure_run first.")
        saved = _run_settings(AppSettings.load())
        requested = {"image": image, "executable": executable, "mpi_processes": mpi_processes, "pull_policy": pull_policy, "memory_limit": memory_limit, "extra_docker_args": extra_docker_args}
        form = validate_run_form_values(RunFormValues(**{**saved, **{key: value for key, value in requested.items() if value}}))
        engine = docker_probe.docker_engine_available()
        if not engine.ok:
            raise AgentError("DOCKER_UNAVAILABLE", f"Docker is not usable: {engine.message}")
        if form.pull_policy == "never" and not docker_probe.image_exists(form.image).ok:
            raise AgentError("IMAGE_NOT_AVAILABLE", f"The image {form.image} is not on this machine and the pull policy is never. Load it first, or name an installed image.")
        run_dir = project_record.create_run_folder()
        job = jobs.start_job(root, "gridpack_run", run_dir, {"form": asdict(form), "notes": notes})
        return {"rows": [job], "run_id": run_dir.name, "job_id": job["job_id"], "next_step": "Call get_status with this job_id and wait_seconds until the run ends."}

    @tool
    def get_status(self, project: str = "", run_id: str = "", job_id: str = "", wait_seconds: int = 0, offset: int = 0, limit: int = 50) -> dict:
        """Show a background job's state, progress, result, and last output lines (job_id), or a run's status, contingency progress parsed from its GridPACK log, last log lines, and latest job (run_id). With neither, list the project's jobs newest first. wait_seconds, at most 1500, waits for the job, or for the run's job, to end."""
        root = self._project(project)
        if run_id and job_id:
            raise AgentError("ONE_TARGET", "Give job_id or run_id, not both.")
        wait = min(max(int(wait_seconds), 0), MAX_WAIT_SECONDS)
        if job_id:
            return {"rows": [jobs.wait_for_job(root, job_id, wait)], "target": "job"}
        if not run_id:
            return {"rows": jobs.list_jobs(root), "target": "jobs"}
        run = resolve_run(root, run_id, completed=False)
        job = next((item for item in jobs.list_jobs(root) if item["run_id"] == run.name), None)
        if job and wait and job["state"] not in jobs.FINAL_STATES:
            job = jobs.wait_for_job(root, job["job_id"], wait)
        status = read_json(run / "status.json") if (run / "status.json").is_file() else {"status": "not started"}
        manifest = read_json(run / "manifest.json") if (run / "manifest.json").is_file() else {}
        parser, progress = GridpackProgressParser(), None
        terminal = run / "work/terminal.log"
        if terminal.is_file():
            with terminal.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    progress = parser.feed(line) or progress
        return {
            "rows": [{"line": text} for text in jobs.log_tail(terminal)], "target": "run", "run_id": run.name, "status": status.get("status"),
            "return_code": status.get("return_code"), "updated_at": status.get("updated_at"),
            "progress": asdict(progress) if progress else None, "container_name": manifest.get("container_name"),
            "gridpack_image": manifest.get("gridpack_image"), "job": {key: job.get(key) for key in ("job_id", "kind", "state", "message")} if job else None,
        }

    @tool
    def stop(self, project: str = "", run_id: str = "", job_id: str = "", confirm: bool = False) -> dict:
        """Stop a background job (job_id), such as an analysis build, or a GridPACK run still running (run_id): its agent job if it has one, else its Docker container. Stopping a GridPACK run's job also stops its container. Stopping something that is running first returns a preview and stops nothing: call again with confirm=True only after the user agrees in a later message."""
        root = self._project(project)
        if bool(run_id) == bool(job_id):
            raise AgentError("ONE_TARGET", "Give the job_id of a job or the run_id of a run to stop.")
        if job_id:
            job = next((item for item in jobs.list_jobs(root) if item["job_id"] == job_id), None)
            if job is not None and job["state"] not in jobs.FINAL_STATES:
                held = self._held("stop", root, {"job_id": job_id}, job["state"], {"rows": [job], "message": f"Job {job_id} ({job['kind']}) is {job['state']}; stopping it ends its work."}, confirm)
                if held is not None:
                    return held
            return {"rows": [jobs.cancel_job(root, job_id)]}
        run = resolve_run(root, run_id, completed=False)
        active = [item for item in jobs.list_jobs(root) if item["run_id"] == run.name and item["kind"] == "gridpack_run" and item["state"] not in jobs.FINAL_STATES]
        running = (read_json(run / "status.json") if (run / "status.json").is_file() else {}).get("status") == "running"
        if active or running:
            target = active[0] if active else {"run_id": run.name, "status": "running"}
            held = self._held("stop", root, {"run_id": run.name}, [target.get("job_id"), target.get("state") or target.get("status")], {"rows": [target], "message": f"Run {run.name} is running; stopping it ends the GridPACK run."}, confirm)
            if held is not None:
                return held
        if active:
            job = jobs.cancel_job(root, active[0]["job_id"])
            return {"rows": [job], "message": f"Job {job['job_id']} is {job['state']}."}
        manifest = read_json(run / "manifest.json") if (run / "manifest.json").is_file() else {}
        result = terminate_gridpack_run(manifest.get("container_name") or gridpack_container_name(run))
        return {"rows": [asdict(result)], "message": result.message}

    @tool
    def run_analysis(self, run_id: str, project: str = "", kind: AnalysisKind = "both", include_index: bool = False, rebuild: bool = False) -> dict:
        """Build a completed run's branch and transformer analysis, as the Analysis tabs do, as a background job. rebuild=True rereads the results even when a cache exists; include_index also builds the per-contingency index."""
        if kind not in ("branch", "transformer", "both"):
            raise AgentError("INVALID_KIND", "Choose branch, transformer, or both.")
        root = self._project(project)
        run = resolve_run(root, run_id)
        kinds = ["branch", "transformer"] if kind == "both" else [kind]
        job = jobs.start_job(root, "analysis", run, {"kinds": kinds, "include_index": include_index, "rebuild": rebuild})
        return {"rows": [job], "job_id": job["job_id"], "next_step": "Call get_status with this job_id and wait_seconds until the analysis ends."}
