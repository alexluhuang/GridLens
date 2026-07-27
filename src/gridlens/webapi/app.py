from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from gridlens.analysis.interactive import build_interactive_analysis_result
from gridlens.analysis.utilization import UtilizationBranchOptions
from gridlens.core.project import Project
from gridlens.core.validation import (
    ValidationError,
    validate_docker_image,
    validate_executable,
    validate_mpi_processes,
)
from gridlens.runner.gridpack_runner import run_gridpack_case
from gridlens.webapi.service import (
    build_run_request,
    ensure_projects_root,
    interactive_analysis_payload,
    list_projects,
    list_runs,
    load_project,
    load_run,
    project_root_for_name,
    project_summary,
    read_text_file,
    run_summary,
)


def _cors_origins_from_env() -> list[str]:
    raw = os.environ.get("GRIDLENS_API_CORS_ORIGINS", "")
    if not raw.strip():
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(slots=True)
class ApiRuntimeState:
    executor: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=4, thread_name_prefix="gridlens-api"))
    lock: Lock = field(default_factory=Lock)
    run_jobs: dict[str, Future[Any]] = field(default_factory=dict)
    analysis_jobs: dict[str, Future[Any]] = field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title="GridLens API", version="0.1.0")
    app.state.projects_root = ensure_projects_root(os.environ.get("GRIDLENS_API_PROJECTS_ROOT"))
    app.state.runtime = ApiRuntimeState()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_from_env(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/projects")
    def get_projects() -> dict[str, Any]:
        return {"projects": list_projects(app.state.projects_root)}

    @app.post("/api/projects")
    async def create_project(
        name: str = Form(...),
        xml_file_name: str = Form(...),
        input_files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        try:
            root_dir = project_root_for_name(app.state.projects_root, name)
            project = Project(name, root_dir)
            root_dir.mkdir(parents=True, exist_ok=True)
            temp_dir = root_dir / ".uploads"
            temp_dir.mkdir(parents=True, exist_ok=True)
            stored_inputs: list[Path] = []
            for upload in input_files:
                destination = temp_dir / Path(upload.filename or "uploaded-file").name
                content = await upload.read()
                destination.write_bytes(content)
                stored_inputs.append(destination)
            project_data = project.save(stored_inputs, xml_file_name)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"project": project_summary(project, project_data)}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        try:
            project, project_data = load_project(app.state.projects_root, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "project": project_summary(project, project_data),
            "runs": list_runs(project, project_data),
        }

    @app.get("/api/projects/{project_id}/runs")
    def get_runs(project_id: str) -> dict[str, Any]:
        try:
            project, project_data = load_project(app.state.projects_root, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"runs": list_runs(project, project_data)}

    @app.post("/api/projects/{project_id}/runs")
    def create_run(
        project_id: str,
        background_tasks: BackgroundTasks,
        image: str = Form("pnnl/gridpack:latest"),
        executable: str = Form("ca.x"),
        xml_file_name: str = Form(""),
        mpi_processes: int = Form(2),
        network_mode: str = Form("none"),
        pull_policy: str = Form("never"),
        use_host_user: bool = Form(True),
        use_platform_flag: bool = Form(True),
        memory_limit: str = Form(""),
        extra_docker_args: str = Form(""),
        container_name: str = Form(""),
        notes: str = Form(""),
    ) -> dict[str, Any]:
        try:
            project, project_data = load_project(app.state.projects_root, project_id)
            request = build_run_request(
                project_data,
                project.create_run_folder(),
                image=validate_docker_image(image),
                executable=validate_executable(executable),
                xml_filename=xml_file_name or project_data.xml_file_name,
                mpi_processes=validate_mpi_processes(mpi_processes),
                network_mode=network_mode,
                pull_policy=pull_policy,
                use_host_user=use_host_user,
                use_platform_flag=use_platform_flag,
                memory_limit=memory_limit,
                extra_docker_args=extra_docker_args,
                container_name=container_name,
                notes=notes,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        future = app.state.runtime.executor.submit(run_gridpack_case, request)
        job_key = f"{project_id}:{request.run_dir.name}"
        with app.state.runtime.lock:
            app.state.runtime.run_jobs[job_key] = future

        background_tasks.add_task(_cleanup_finished_job, app.state.runtime.run_jobs, app.state.runtime.lock, job_key)
        return {"run": run_summary(project, project_data, request.run_dir)}

    @app.get("/api/projects/{project_id}/runs/{run_id}")
    def get_run(project_id: str, run_id: str) -> dict[str, Any]:
        try:
            reference = load_run(app.state.projects_root, project_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"run": run_summary(reference.project, reference.project_data, reference.run_dir)}

    @app.get("/api/projects/{project_id}/runs/{run_id}/log", response_class=PlainTextResponse)
    def get_run_log(project_id: str, run_id: str) -> str:
        try:
            reference = load_run(app.state.projects_root, project_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return read_text_file(reference.run_dir / "logs" / "run.log")

    @app.post("/api/projects/{project_id}/runs/{run_id}/analysis/interactive")
    def create_interactive_analysis(
        project_id: str,
        run_id: str,
        include_nontransformer_branches: bool = Form(True),
        include_two_winding_transformers: bool = Form(False),
        include_three_winding_transformers: bool = Form(False),
        include_transformer_equivalents: bool = Form(False),
    ) -> dict[str, Any]:
        try:
            reference = load_run(app.state.projects_root, project_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        branch_options = UtilizationBranchOptions(
            include_nontransformer_branches=include_nontransformer_branches,
            include_two_winding_transformers=include_two_winding_transformers,
            include_three_winding_transformers=include_three_winding_transformers,
            include_transformer_equivalents=include_transformer_equivalents,
        )
        try:
            analysis = build_interactive_analysis_result(reference.run_dir, branch_options)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Interactive analysis failed: {exc}") from exc
        return {
            "analysis": interactive_analysis_payload(
                analysis,
                project_id=project_id,
                project_name=reference.project_data.name,
                run_id=run_id,
                branch_options=branch_options,
            )
        }

    return app


def _cleanup_finished_job(job_store: dict[str, Future[Any]], lock: Lock, job_key: str) -> None:
    with lock:
        future = job_store.get(job_key)
        if future is not None and future.done():
            job_store.pop(job_key, None)
