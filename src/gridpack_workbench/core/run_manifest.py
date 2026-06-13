from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import platform
from pathlib import Path


def detect_docker_platform() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "linux/amd64"
    if machine in ("aarch64", "arm64"):
        return "linux/arm64"
    return ""


def detect_host_architecture() -> str:
    return platform.machine().lower()


@dataclass(slots=True)
class RunManifest:
    run_id: str
    created_at: str
    project_name: str
    gridpack_image: str
    gridpack_executable: str
    xml_file: str
    mpi_processes: int
    docker_platform: str
    host_architecture: str
    network_mode: str
    pull_policy: str
    command: list[str]
    input_files: list[dict] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def now(
        cls,
        run_dir: Path,
        project_name: str,
        gridpack_image: str,
        gridpack_executable: str,
        xml_file: str,
        mpi_processes: int,
        network_mode: str,
        pull_policy: str,
        command: list[str],
        input_files: list[dict] | None = None,
        notes: str = "",
    ) -> "RunManifest":
        return cls(
            run_id=run_dir.name,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            project_name=project_name,
            gridpack_image=gridpack_image,
            gridpack_executable=gridpack_executable,
            xml_file=xml_file,
            mpi_processes=mpi_processes,
            docker_platform=detect_docker_platform(),
            host_architecture=detect_host_architecture(),
            network_mode=network_mode,
            pull_policy=pull_policy,
            command=command,
            input_files=input_files or [],
            notes=notes,
        )

    def save(self, run_dir: Path) -> Path:
        path = run_dir / "manifest.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path
