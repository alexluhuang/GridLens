# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()

a = Analysis(
    [str(project_root / "src" / "gridpack_workbench" / "main.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (
            str(project_root / "src" / "gridpack_workbench" / "resources"),
            "gridpack_workbench/resources",
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
    name="GridPACKWorkbench",
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
    name="GridPACKWorkbench",
)
