from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import logging

from gridlens.analysis.interactive import AnalysisBuildResult
from gridlens.analysis.utilization import UtilizationBranchOptions
from gridlens.core.project import PROJECT_FILE_NAME, Project, ProjectData, open_project, safe_folder_name
from gridlens.runner.gridpack_runner import GridpackRunRequest


DEFAULT_WEB_PROJECTS_ROOT = Path("~/GridLensWebProjects").expanduser()
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class RunReference:
    project_id: str
    project: Project
    project_data: ProjectData
    run_id: str
    run_dir: Path


def ensure_projects_root(root: str | Path | None = None) -> Path:
    projects_root = Path(root or DEFAULT_WEB_PROJECTS_ROOT).expanduser().resolve()
    projects_root.mkdir(parents=True, exist_ok=True)
    return projects_root


def project_root_for_name(projects_root: str | Path, project_name: str) -> Path:
    return ensure_projects_root(projects_root) / safe_folder_name(project_name)


def list_projects(projects_root: str | Path) -> list[dict[str, Any]]:
    root = ensure_projects_root(projects_root)
    projects: list[dict[str, Any]] = []
    for project_file in sorted(root.glob(f"*/{PROJECT_FILE_NAME}")):
        try:
            project, project_data = open_project(project_file)
        except Exception as exc:
            LOGGER.warning("Skipping unreadable GridLens project file %s: %s", project_file, exc)
            continue
        projects.append(project_summary(project, project_data))
    projects.sort(key=lambda item: str(item["updated_at"]), reverse=True)
    return projects


def load_project(projects_root: str | Path, project_id: str) -> tuple[Project, ProjectData]:
    project_file = ensure_projects_root(projects_root) / project_id / PROJECT_FILE_NAME
    if not project_file.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    return open_project(project_file)


def project_summary(project: Project, project_data: ProjectData) -> dict[str, Any]:
    runs = project.list_runs()
    return {
        "project_id": project.root_dir.name,
        "name": project_data.name,
        "root_dir": str(project.root_dir),
        "xml_file_name": project_data.xml_file_name,
        "input_files": [record.file_name for record in project_data.input_files],
        "run_count": len(runs),
        "created_at": project_data.created_at,
        "updated_at": project_data.updated_at,
        "latest_run_id": runs[0].name if runs else "",
    }


def list_runs(project: Project, project_data: ProjectData) -> list[dict[str, Any]]:
    return [run_summary(project, project_data, run_dir) for run_dir in project.list_runs()]


def load_run(projects_root: str | Path, project_id: str, run_id: str) -> RunReference:
    project, project_data = load_project(projects_root, project_id)
    run_dir = project.runs_dir / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run not found: {project_id}/{run_id}")
    return RunReference(
        project_id=project_id,
        project=project,
        project_data=project_data,
        run_id=run_id,
        run_dir=run_dir,
    )


def read_run_status(run_dir: str | Path) -> dict[str, Any]:
    status_path = Path(run_dir) / "status.json"
    if not status_path.exists():
        return {"status": "not started", "updated_at": "", "return_code": None, "error": ""}
    try:
        raw = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown", "updated_at": "", "return_code": None, "error": "invalid status.json"}
    return {
        "status": str(raw.get("status") or "unknown"),
        "updated_at": str(raw.get("updated_at") or ""),
        "return_code": raw.get("return_code"),
        "error": str(raw.get("error") or ""),
    }


def read_text_file(path: str | Path, *, max_bytes: int = 512_000) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    data = file_path.read_bytes()
    return data[-max_bytes:].decode("utf-8", errors="replace")


def run_summary(project: Project, project_data: ProjectData, run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir).expanduser().resolve()
    status = read_run_status(path)
    return {
        "project_id": project.root_dir.name,
        "project_name": project_data.name,
        "run_id": path.name,
        "run_dir": str(path),
        "status": status["status"],
        "updated_at": status["updated_at"],
        "return_code": status["return_code"],
        "error": status["error"],
        "manifest_file": str(path / "manifest.json"),
        "log_file": str(path / "logs" / "run.log"),
        "work_dir": str(path / "work"),
        "report_dir": str(path / "reports"),
    }


def build_run_request(
    project_data: ProjectData,
    run_dir: Path,
    *,
    image: str,
    executable: str,
    xml_filename: str,
    mpi_processes: int,
    network_mode: str = "none",
    pull_policy: str = "never",
    use_host_user: bool = True,
    use_platform_flag: bool = True,
    memory_limit: str = "",
    extra_docker_args: str = "",
    container_name: str = "",
    notes: str = "",
) -> GridpackRunRequest:
    return GridpackRunRequest(
        project_data=project_data,
        run_dir=run_dir,
        image=image,
        executable=executable,
        xml_filename=xml_filename,
        mpi_processes=mpi_processes,
        network_mode=network_mode,
        pull_policy=pull_policy,
        use_host_user=use_host_user,
        use_platform_flag=use_platform_flag,
        memory_limit=memory_limit,
        extra_docker_args=extra_docker_args,
        container_name=container_name,
        notes=notes,
    )


def interactive_analysis_payload(
    analysis: AnalysisBuildResult,
    *,
    project_id: str,
    project_name: str,
    run_id: str,
    branch_options: UtilizationBranchOptions,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "project_name": project_name,
        "run_id": run_id,
        "generated_at": analysis.dataset.generated_at,
        "branch_options": {
            "include_nontransformer_branches": branch_options.include_nontransformer_branches,
            "include_two_winding_transformers": branch_options.include_two_winding_transformers,
            "include_three_winding_transformers": branch_options.include_three_winding_transformers,
            "include_transformer_equivalents": branch_options.include_transformer_equivalents,
        },
        "line_rows": analysis.line_rows,
        "max_line_rows": analysis.max_line_rows,
        "control_area_rows": analysis.control_area_rows,
        "voltage_group_rows": analysis.voltage_group_rows,
        "table_names": sorted(analysis.dataset.tables.keys()),
        "report_dir": str(analysis.dataset.report_dir),
        "manifest_path": str(analysis.dataset.manifest_path),
    }
