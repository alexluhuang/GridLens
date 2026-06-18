from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import subprocess
from typing import Callable

from gridpack_workbench.core.project import ProjectData, copy_project_inputs_to_run, file_sha256
from gridpack_workbench.core.run_manifest import ManifestInputFile, RunManifest
from gridpack_workbench.runner.docker_command import build_gridpack_docker_command


LogCallback = Callable[[str], None]


@dataclass(slots=True)
class GridpackRunRequest:
    project_data: ProjectData
    run_dir: Path
    image: str
    executable: str
    xml_filename: str
    mpi_processes: int
    network_mode: str = "none"
    pull_policy: str = "never"
    use_host_user: bool = True
    use_platform_flag: bool = True
    memory_limit: str = ""
    extra_docker_args: str = ""
    notes: str = ""


@dataclass(slots=True)
class GridpackRunResult:
    return_code: int
    run_dir: Path
    log_file: Path
    terminal_log_file: Path
    status_file: Path
    manifest_file: Path


@dataclass(slots=True)
class GridpackRunFiles:
    run_dir: Path
    work_dir: Path
    logs_dir: Path
    reports_dir: Path
    log_file: Path
    terminal_log_file: Path
    status_file: Path

    @classmethod
    def for_run(cls, run_dir: Path) -> GridpackRunFiles:
        resolved_run_dir = Path(run_dir).expanduser().resolve()
        work_dir = resolved_run_dir / "work"
        logs_dir = resolved_run_dir / "logs"
        return cls(
            run_dir=resolved_run_dir,
            work_dir=work_dir,
            logs_dir=logs_dir,
            reports_dir=resolved_run_dir / "reports",
            log_file=logs_dir / "run.log",
            terminal_log_file=work_dir / "terminal.log",
            status_file=resolved_run_dir / "status.json",
        )

    def create_directories(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


def _write_status(path: Path, status: str, return_code: int | None = None, error: str = "") -> None:
    data = {
        "status": status,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if return_code is not None:
        data["return_code"] = return_code
    if error:
        data["error"] = error
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _input_manifest_records(work_dir: Path) -> list[ManifestInputFile]:
    records = []
    for path in sorted(work_dir.iterdir()):
        if not path.is_file():
            continue
        records.append(
            ManifestInputFile(
                file_name=path.name,
                path_in_container=f"/app/workspace/{path.name}",
                size_bytes=path.stat().st_size,
                sha256=file_sha256(path),
            )
        )
    return records


def run_gridpack_case(request: GridpackRunRequest, log_callback: LogCallback | None = None) -> GridpackRunResult:
    files = GridpackRunFiles.for_run(request.run_dir)
    files.create_directories()

    copy_project_inputs_to_run(request.project_data, files.run_dir)
    command = build_gridpack_docker_command(
        work_dir=files.work_dir,
        image=request.image,
        executable=request.executable,
        xml_filename=request.xml_filename,
        mpi_processes=request.mpi_processes,
        network_mode=request.network_mode,
        pull_policy=request.pull_policy,
        use_host_user=request.use_host_user,
        use_platform_flag=request.use_platform_flag,
        memory_limit=request.memory_limit,
        extra_docker_args=request.extra_docker_args,
    )

    manifest = RunManifest.now(
        run_dir=files.run_dir,
        project_name=request.project_data.name,
        gridpack_image=request.image,
        gridpack_executable=request.executable,
        xml_file=request.xml_filename,
        mpi_processes=request.mpi_processes,
        network_mode=request.network_mode,
        pull_policy=request.pull_policy,
        command=command,
        input_files=_input_manifest_records(files.work_dir),
        notes=request.notes,
    )
    manifest_file = manifest.save(files.run_dir)
    _write_status(files.status_file, "running")

    with (
        files.log_file.open("w", encoding="utf-8") as log,
        files.terminal_log_file.open("w", encoding="utf-8") as terminal_log,
    ):
        log.write("COMMAND:\n")
        log.write(" ".join(command) + "\n\n")
        terminal_log.write("COMMAND:\n")
        terminal_log.write(" ".join(command) + "\n\n")
        log.flush()
        terminal_log.flush()

        if log_callback:
            log_callback("Starting Docker run...\n")

        try:
            process = subprocess.Popen(
                command,
                cwd=str(files.work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            failure_message = f"Docker run could not be started: {exc}\n"
            log.write(failure_message)
            terminal_log.write(failure_message)
            log.flush()
            terminal_log.flush()
            if log_callback:
                log_callback(failure_message)
            _write_status(files.status_file, "failed", error=str(exc))
            raise

        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            terminal_log.write(line)
            log.flush()
            terminal_log.flush()
            if log_callback:
                log_callback(line)

        return_code = process.wait()

    status = "completed" if return_code == 0 else "failed"
    _write_status(files.status_file, status, return_code=return_code)

    return GridpackRunResult(
        return_code=return_code,
        run_dir=files.run_dir,
        log_file=files.log_file,
        terminal_log_file=files.terminal_log_file,
        status_file=files.status_file,
        manifest_file=manifest_file,
    )
