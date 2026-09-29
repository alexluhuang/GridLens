from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from gridlens.core.validation import ValidationError, sanitize_project_name


PROJECT_FILE_NAME = "project.json"
RESERVED_PROJECT_ROOT_NAMES = {"exports", "logs", "original_inputs", "reports", "runs", "work"}
# A GridPACK configuration is a few kilobytes; a larger XML input is data, such as a contingency list.
MAX_CONFIGURATION_XML_BYTES = 1024 * 1024


def utc_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_folder_name(name: str) -> str:
    safe = []
    for char in sanitize_project_name(name):
        if char.isalnum() or char in ("-", "_", "."):
            safe.append(char)
        elif char.isspace():
            safe.append("_")
    return "".join(safe).strip("_") or "GridPACK_Project"


def is_gridpack_configuration_root(root: ET.Element) -> bool:
    """Return whether an XML root is a GridPACK run configuration rather than another XML input.

    A configuration is a <Configuration> element with a power-flow section, or a contingency-analysis
    section holding settings. A contingency list is also a <Configuration>, but its contingency-analysis
    section holds only <Contingencies>.
    """
    if root.tag != "Configuration":
        return False
    if root.find("Powerflow") is not None:
        return True
    contingency = root.find("Contingency_analysis")
    return contingency is not None and any(isinstance(child.tag, str) and child.tag != "Contingencies" for child in contingency)


def is_gridpack_configuration_file(path: str | Path) -> bool:
    """Return whether path is an .xml file holding a GridPACK run configuration; unreadable files are not."""
    path = Path(path)
    try:
        if path.suffix.lower() != ".xml" or not path.is_file() or path.stat().st_size > MAX_CONFIGURATION_XML_BYTES:
            return False
        return is_gridpack_configuration_root(ET.parse(path).getroot())
    except (OSError, ET.ParseError, ValueError):
        return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_project_root_dir(root_dir: str | Path) -> Path:
    resolved = Path(root_dir).expanduser().resolve()
    if resolved.name in RESERVED_PROJECT_ROOT_NAMES:
        raise ValidationError(
            f"Project folder cannot be the managed `{resolved.name}` folder. "
            "Choose the top-level project folder instead."
        )

    for parent in resolved.parents:
        if (parent / PROJECT_FILE_NAME).exists():
            raise ValidationError(
                f"Project folder is inside an existing GridLens project: {parent}. "
                "Choose that top-level project folder instead."
            )
        if parent.name in RESERVED_PROJECT_ROOT_NAMES:
            raise ValidationError(
                f"Project folder cannot be inside the managed `{parent.name}` folder. "
                "Choose the top-level project folder instead."
            )

    return resolved


@dataclass(slots=True)
class InputFileRecord:
    file_name: str
    source_path: str
    stored_path: str
    sha256: str
    size_bytes: int
    imported_at: str


@dataclass(slots=True)
class ProjectData:
    name: str
    root_dir: str
    created_at: str
    updated_at: str
    xml_file_name: str = ""
    input_files: list[InputFileRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectData":
        records = [InputFileRecord(**item) for item in data.get("input_files", [])]
        return cls(
            name=data["name"],
            root_dir=data["root_dir"],
            created_at=data["created_at"],
            updated_at=data.get("updated_at", data["created_at"]),
            xml_file_name=data.get("xml_file_name", ""),
            input_files=records,
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


class Project:
    def __init__(self, name: str, root_dir: str | Path):
        self.name = sanitize_project_name(name)
        self.root_dir = validate_project_root_dir(root_dir)

    @property
    def project_file(self) -> Path:
        return self.root_dir / PROJECT_FILE_NAME

    @property
    def original_inputs_dir(self) -> Path:
        return self.root_dir / "original_inputs"

    @property
    def runs_dir(self) -> Path:
        return self.root_dir / "runs"

    @property
    def exports_dir(self) -> Path:
        return self.root_dir / "exports"

    def create_directories(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.original_inputs_dir.mkdir(exist_ok=True)
        self.runs_dir.mkdir(exist_ok=True)
        self.exports_dir.mkdir(exist_ok=True)

    def save(self, input_files: list[Path], xml_file_name: str) -> ProjectData:
        _validate_project_inputs(input_files, xml_file_name)
        self.create_directories()
        existing = self.load_data() if self.project_file.exists() else None
        created_at = existing.created_at if existing else utc_timestamp()

        previous = {record.file_name: record for record in existing.input_files} if existing else {}
        records = []
        for file_path in input_files:
            stored_path = self.original_inputs_dir / file_path.name
            source_path = str(file_path)
            if file_path.resolve() != stored_path.resolve():
                shutil.copy2(file_path, stored_path)
            elif file_path.name in previous:
                # Saving the project again lists its stored copy; keep where the file first came from.
                source_path = previous[file_path.name].source_path
            records.append(
                InputFileRecord(
                    file_name=stored_path.name,
                    source_path=source_path,
                    stored_path=str(stored_path),
                    sha256=file_sha256(stored_path),
                    size_bytes=stored_path.stat().st_size,
                    imported_at=utc_timestamp(),
                )
            )

        data = ProjectData(
            name=self.name,
            root_dir=str(self.root_dir),
            created_at=created_at,
            updated_at=utc_timestamp(),
            xml_file_name=xml_file_name,
            input_files=records,
        )
        self.project_file.write_text(json.dumps(data.to_dict(), indent=2), encoding="utf-8")
        return data

    def save_generated_xml(self, project_data: ProjectData, xml_file_name: str, xml_text: str) -> ProjectData:
        _validate_generated_xml_name(xml_file_name)
        self.create_directories()
        xml_path = self.original_inputs_dir / xml_file_name
        xml_path.write_text(xml_text, encoding="utf-8")

        previous = next((record for record in project_data.input_files if record.file_name == xml_path.name), None)
        generated_record = InputFileRecord(
            file_name=xml_path.name,
            # A configuration attached from elsewhere and then edited here keeps the record of where it came from.
            source_path=previous.source_path if previous else str(xml_path),
            stored_path=str(xml_path),
            sha256=file_sha256(xml_path),
            size_bytes=xml_path.stat().st_size,
            imported_at=utc_timestamp(),
        )
        records = _upsert_input_file_record(project_data.input_files, generated_record)
        data = ProjectData(
            name=project_data.name,
            root_dir=project_data.root_dir,
            created_at=project_data.created_at,
            updated_at=utc_timestamp(),
            xml_file_name=xml_path.name,
            input_files=records,
        )
        self.project_file.write_text(json.dumps(data.to_dict(), indent=2), encoding="utf-8")
        return data

    def load_data(self) -> ProjectData:
        raw = json.loads(self.project_file.read_text(encoding="utf-8"))
        return ProjectData.from_dict(raw)

    def create_run_folder(self) -> Path:
        self.create_directories()
        base_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = self.runs_dir / base_id
        suffix = 2
        while run_dir.exists():
            run_dir = self.runs_dir / f"{base_id}_{suffix}"
            suffix += 1

        (run_dir / "work").mkdir(parents=True)
        (run_dir / "logs").mkdir()
        (run_dir / "reports").mkdir()
        return run_dir

    def list_runs(self) -> list[Path]:
        if not self.runs_dir.exists():
            return []
        return sorted([path for path in self.runs_dir.iterdir() if path.is_dir()], reverse=True)


def open_project(project_file: str | Path) -> tuple[Project, ProjectData]:
    path = Path(project_file).expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = ProjectData.from_dict(raw)
    project = Project(data.name, data.root_dir)
    return project, data


def _validate_project_inputs(input_files: list[Path], xml_file_name: str) -> None:
    file_names = [path.name for path in input_files]
    duplicates = sorted(name for name, count in Counter(file_names).items() if count > 1)
    if duplicates:
        duplicate_list = ", ".join(duplicates)
        raise ValidationError(f"Project input files must have unique file names. Duplicates: {duplicate_list}")
    if not xml_file_name:
        return
    if xml_file_name not in file_names:
        raise ValidationError("The saved XML file must be one of the project input files.")


def _validate_generated_xml_name(xml_file_name: str) -> None:
    if Path(xml_file_name).name != xml_file_name or Path(xml_file_name).suffix.lower() != ".xml":
        raise ValidationError("Generated XML file name must be a local .xml file name.")


def _upsert_input_file_record(
    records: list[InputFileRecord],
    generated_record: InputFileRecord,
) -> list[InputFileRecord]:
    updated = []
    replaced = False
    for record in records:
        if record.file_name == generated_record.file_name:
            updated.append(generated_record)
            replaced = True
        else:
            updated.append(record)
    if not replaced:
        updated.append(generated_record)
    return updated


def copy_project_inputs_to_run(project_data: ProjectData, run_dir: Path) -> list[Path]:
    work_dir = run_dir / "work"
    copied = []
    for record in project_data.input_files:
        source = Path(record.stored_path)
        if not source.exists():
            raise FileNotFoundError(f"Project input file is missing: {source}")
        destination = work_dir / source.name
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied
