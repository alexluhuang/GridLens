# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()

a = Analysis(
    [str(project_root / "src" / "gridlens" / "main.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (
            str(project_root / "src" / "gridlens" / "resources"),
            "gridlens/resources",
        )
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GridLens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GridLens",
)
