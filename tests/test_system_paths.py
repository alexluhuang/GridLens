"""GridLens folders follow each platform's conventions."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from gridlens.system import paths

posix_only = pytest.mark.skipif(os.name == "nt", reason="XDG applies to Linux")
windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows folders")


@posix_only
def test_linux_folders_follow_the_xdg_variables(tmp_path, monkeypatch) -> None:
    for variable in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / variable))

    assert paths.config_dir() == tmp_path / "XDG_CONFIG_HOME" / "gridlens"
    assert paths.cache_dir() == tmp_path / "XDG_CACHE_HOME" / "gridlens"
    assert paths.data_dir() == tmp_path / "XDG_DATA_HOME" / "gridlens"


@posix_only
def test_linux_folders_default_to_the_home_folder(monkeypatch) -> None:
    for variable in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(variable, raising=False)
    home = Path.home()

    assert paths.config_dir() == home / ".config" / "gridlens"
    assert paths.cache_dir() == home / ".cache" / "gridlens"
    assert paths.data_dir() == home / ".local" / "share" / "gridlens"


@posix_only
def test_linux_processes_share_tmp_whatever_tmpdir_says(monkeypatch) -> None:
    monkeypatch.setenv("TMPDIR", "/var/tmp")

    assert paths.shared_temp_dir() == Path("/tmp")


@windows_only
def test_windows_folders_are_under_local_app_data(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert paths.config_dir() == tmp_path / "GridLens"
    assert paths.cache_dir() == tmp_path / "GridLens" / "cache"
    assert paths.data_dir() == tmp_path / "GridLens"
