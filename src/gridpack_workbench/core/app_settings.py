from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import os
from pathlib import Path


def _default_projects_dir() -> Path:
    return Path.home() / "GridPACKWorkbenchProjects"


def _default_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "gridpack-workbench"
    return Path.home() / ".config" / "gridpack-workbench"


@dataclass(slots=True)
class AppSettings:
    app_name: str = "GridPACK Workbench"
    default_gridpack_image: str = "pnnl/gridpack:latest"
    default_executable: str = "ca.x"
    default_xml_file: str = "input.xml"
    default_mpi_processes: int = 4
    default_projects_dir: Path = field(default_factory=_default_projects_dir)
    docker_network_mode: str = "none"
    docker_pull_policy: str = "never"
    use_platform_flag: bool = True
    use_host_user: bool = True
    memory_limit: str = ""
    extra_docker_args: str = ""

    @classmethod
    def config_path(cls) -> Path:
        return _default_config_dir() / "settings.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "AppSettings":
        settings_path = path or cls.config_path()
        if not settings_path.exists():
            return cls()

        raw = json.loads(settings_path.read_text(encoding="utf-8"))
        values = {}
        field_names = {field.name for field in fields(cls)}
        for key, value in raw.items():
            if key not in field_names:
                continue
            if key == "default_projects_dir":
                values[key] = Path(value).expanduser()
            else:
                values[key] = value
        return cls(**values)

    def save(self, path: Path | None = None) -> Path:
        settings_path = path or self.config_path()
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["default_projects_dir"] = str(self.default_projects_dir)
        settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return settings_path
