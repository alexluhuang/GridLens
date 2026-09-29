from __future__ import annotations

import re
from pathlib import Path


_PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_. -]{0,98}[A-Za-z0-9])?$")
# Windows reserves these names for devices, with or without an extension, in
# any case, so no file or folder there can have one.
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)


class ValidationError(ValueError):
    """Raised when user-provided project or run inputs are not usable."""


def sanitize_project_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise ValidationError("Project name is required.")
    if not _PROJECT_NAME_PATTERN.match(cleaned):
        raise ValidationError(
            "Project names must start and end with a letter or number and use only "
            "letters, numbers, spaces, dots, underscores, and hyphens."
        )
    return cleaned


def is_windows_reserved_name(name: str) -> bool:
    """Return True for a file or folder name that Windows cannot create."""
    stem = name.split(".", 1)[0].rstrip(" ")
    return stem.upper() in WINDOWS_RESERVED_NAMES


def validate_existing_file(path: str | Path, label: str = "File") -> Path:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ValidationError(f"{label} does not exist: {file_path}")
    if not file_path.is_file():
        raise ValidationError(f"{label} is not a file: {file_path}")
    return file_path.resolve()


def validate_existing_files(paths: list[str | Path]) -> list[Path]:
    if not paths:
        raise ValidationError("At least one input file is required.")
    return [validate_existing_file(path, "Input file") for path in paths]


def validate_mpi_processes(value: int) -> int:
    if value < 1:
        raise ValidationError("MPI process count must be at least 1.")
    if value > 4096:
        raise ValidationError("MPI process count is unexpectedly high. Use 4096 or fewer.")
    return value


def validate_docker_image(image: str) -> str:
    image = image.strip()
    if not image:
        raise ValidationError("Docker image is required.")
    if any(char.isspace() for char in image):
        raise ValidationError("Docker image cannot contain whitespace.")
    return image


def validate_executable(executable: str) -> str:
    executable = executable.strip()
    if not executable:
        raise ValidationError("GridPACK executable is required.")
    if "\x00" in executable:
        raise ValidationError("GridPACK executable contains an invalid character.")
    return executable
