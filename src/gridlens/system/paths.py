"""The folders GridLens keeps its settings, caches, data, and locks in.

On Linux they follow the XDG base-directory conventions, under a `gridlens`
folder. On Windows they are under `%LOCALAPPDATA%\\GridLens`, which belongs to
one user on one machine; settings name local paths, so they do not roam.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


def config_dir() -> Path:
    """Return the folder that holds settings.json."""
    if os.name == "nt":
        return _windows_root()
    return _xdg_dir("XDG_CONFIG_HOME", Path(".config"))


def cache_dir() -> Path:
    """Return the folder for files GridLens can rebuild, such as logs."""
    if os.name == "nt":
        return _windows_root() / "cache"
    return _xdg_dir("XDG_CACHE_HOME", Path(".cache"))


def data_dir() -> Path:
    """Return the folder for programs GridLens installs, such as Ollama."""
    if os.name == "nt":
        return _windows_root()
    return _xdg_dir("XDG_DATA_HOME", Path(".local") / "share")


def shared_temp_dir() -> Path:
    """Return the temporary folder that every GridLens process agrees on.

    Locks and scratch space live here, so the GUI, the tool server, and job
    workers must name the same folder even if their environments differ. On
    POSIX that is /tmp itself, whatever TMPDIR says. On Windows it is the
    user's own temporary folder, which each process finds through TEMP.
    """
    if os.name == "nt":
        return Path(tempfile.gettempdir())
    return Path("/tmp")


def _windows_root() -> Path:
    """Return %LOCALAPPDATA%\\GridLens."""
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "GridLens"


def _xdg_dir(variable: str, default: Path) -> Path:
    """Return the gridlens folder under an XDG base directory."""
    base = os.environ.get(variable)
    return (Path(base) if base else Path.home() / default) / "gridlens"
