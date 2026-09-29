"""The Windows bundle has a console helper, an icon, and a per-user installer.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from gridlens.agent import process as agent_process

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_the_spec_builds_a_console_helper_and_no_rapids_on_windows() -> None:
    spec = _read("packaging/pyinstaller/gridlens.spec")

    assert 'name="gridlens-cli"' in spec
    assert "console=True" in spec
    assert "if not WINDOWS:" in spec
    assert "upx=True" not in spec
    assert 'find_spec("_numba_cuda_redirector")' in spec


def test_the_installer_needs_no_administrator(tmp_path) -> None:
    script = _read("packaging/windows/gridlens.iss")

    assert "PrivilegesRequired=lowest" in script
    assert "ArchitecturesAllowed=x64compatible" in script
    assert r"..\..\dist\GridLens" in script


def test_the_icon_holds_every_windows_size(tmp_path) -> None:
    pytest.importorskip("PIL")
    icon = tmp_path / "gridlens.ico"

    subprocess.run(
        [sys.executable, str(ROOT / "packaging/windows/make_icon.py"),
         str(icon)], check=True, timeout=120)

    from PIL import Image
    with Image.open(icon) as image:
        assert image.format == "ICO"
        assert (256, 256) in image.info["sizes"]
        assert (16, 16) in image.info["sizes"]


def test_frozen_windows_builds_run_stdio_entry_points_from_the_helper(
        tmp_path, monkeypatch) -> None:
    application = tmp_path / "GridLens.exe"
    helper = tmp_path / agent_process.CONSOLE_EXECUTABLE
    application.write_text("")
    helper.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(application))
    monkeypatch.setattr(agent_process.processes, "WINDOWS", True)

    assert agent_process.mcp_command() == [str(helper), "--mcp-server"]


def test_frozen_linux_builds_run_every_entry_point_from_one_executable(
        tmp_path, monkeypatch) -> None:
    application = tmp_path / "GridLens"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(application))
    monkeypatch.setattr(agent_process.processes, "WINDOWS", False)

    assert agent_process.mcp_command() == [str(application), "--mcp-server"]
