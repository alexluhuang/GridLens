# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import re
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata
import importlib.util

project_root = Path.cwd()
# RAPIDS publishes Linux wheels only, so a Windows bundle carries the CPU
# analysis stack. Windows also needs a console executable for the entry
# points that talk over stdio, an .ico icon, and a version resource.
WINDOWS = sys.platform == "win32"
ICON = project_root / "build" / "gridlens.ico"


def _runtime_submodule(module_name):
    excluded_parts = (".tests", ".testing", ".benchmarks", ".conftest")
    return not any(part in module_name for part in excluded_parts)


def _collect_all(package):
    try:
        return collect_all(package, filter_submodules=_runtime_submodule)
    except Exception:
        return [], [], []


def _collect_dynamic_libs(package, destdir=None):
    try:
        return collect_dynamic_libs(package, destdir=destdir)
    except Exception:
        return []


def _collect_data_files(package, includes):
    try:
        return collect_data_files(package, includes=includes)
    except Exception:
        return []


def _collect_library_globs(package, patterns, destdir="."):
    spec = importlib.util.find_spec(package)
    if not spec or not spec.submodule_search_locations:
        return []
    files = []
    for root in spec.submodule_search_locations:
        package_root = Path(root)
        for pattern in patterns:
            files += [(str(path), destdir) for path in package_root.glob(pattern) if path.is_file()]
    return files


def _collect_package_relative_files(package, patterns):
    spec = importlib.util.find_spec(package)
    if not spec or not spec.submodule_search_locations:
        return []
    files = []
    package_dest = Path(*package.split("."))
    for root in spec.submodule_search_locations:
        package_root = Path(root)
        for pattern in patterns:
            for path in package_root.glob(pattern):
                if path.is_file():
                    files.append((str(path), str(package_dest / path.parent.relative_to(package_root))))
    return files


def _copy_metadata(package):
    try:
        return copy_metadata(package)
    except Exception:
        return []


analysis_packages = ("matplotlib", "pandas", "dask", "distributed", "pyarrow")
rapids_packages = (
    "cuda",
    "cudf",
    "cupy",
    "cupy_backends",
    "cupyx",
    "dask_cuda",
    "dask_cudf",
    "numba_cuda",
    "nvtx",
    "pylibcudf",
    "rmm",
)
native_library_packages = (
    "cuda",
    "cudf",
    "cupy",
    "cupy_backends",
    "nvidia",
    "pylibcudf",
    "rmm",
)
rapids_loader_library_packages = (
    "libcudf",
    "libkvikio",
    "librmm",
    "rapids_logger",
)
metadata_packages = (
    "mcp",
    *analysis_packages,
    "cuda-bindings",
    "cuda-core",
    "cuda-python",
    "cuda-toolkit",
    "cudf-cu13",
    "cupy-cuda13x",
    "dask-cuda",
    "dask-cudf-cu13",
    "libcudf-cu13",
    "libkvikio-cu13",
    "librmm-cu13",
    "numba-cuda",
    "nvtx",
    "nvidia-cuda-runtime",
    "nvidia-libnvcomp-cu13",
    "nvidia-nccl-cu13",
    "pylibcudf-cu13",
    "rapids-dask-dependency",
    "rapids-logger",
    "rmm-cu13",
)
hidden_imports = [
    "mcp.server.fastmcp",
    "mcp.server.stdio",
    "_numba_cuda_redirector",
    "dask",
    "dask.dataframe",
    "dask_cuda",
    "dask_cudf",
    "distributed",
    "distributed.client",
    "distributed.deploy.local",
    "distributed.system",
    "graphlib",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.figure",
    "nvtx.colors",
    "nvtx._lib.lib",
    "nvtx._lib.profiler",
    "pandas",
    "pyarrow",
    "pyarrow.parquet",
    "cudf",
    "cudf.pandas",
    "cupy",
    "pylibcudf",
    "rmm",
]
metadata_files = []
data_files = []
binary_files = []
if not WINDOWS:
    for package in rapids_packages:
        datas, binaries, collected_hidden_imports = _collect_all(package)
        data_files += datas
        binary_files += binaries
        hidden_imports += collected_hidden_imports
    for package in native_library_packages:
        binary_files += _collect_dynamic_libs(package, destdir=".")
    for package in rapids_loader_library_packages:
        data_files += _collect_data_files(
            package, includes=["VERSION", "GIT_COMMIT"])
        binary_files += _collect_dynamic_libs(package)
    binary_files += _collect_package_relative_files("numba_cuda", ["**/*.so"])
    binary_files += _collect_package_relative_files("cuda", ["**/*.so"])
    binary_files += _collect_library_globs("nvidia.cu13", ["lib/lib*.so*"])
    binary_files += _collect_library_globs(
        "nvidia.libnvcomp", ["lib64/lib*.so*"])
    binary_files += _collect_library_globs(
        "nvidia.nccl", ["lib/lib*.so*", "lib64/lib*.so*"])
for package in metadata_packages:
    metadata_files += _copy_metadata(package)
# numba-cuda's runtime hook imports its redirector, so it runs only where
# numba-cuda is installed; a bundle without it would fail at startup.
runtime_hooks = []
if importlib.util.find_spec("_numba_cuda_redirector"):
    hooks = project_root / "packaging" / "pyinstaller" / "runtime_hooks"
    runtime_hooks.append(str(hooks / "numba_cuda_redirector.py"))
else:
    hidden_imports.remove("_numba_cuda_redirector")


def _version_resource():
    """Return the Windows version resource for the project's version."""
    from PyInstaller.utils.win32 import versioninfo

    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', text, re.MULTILINE).group(1)
    numbers = tuple(int(part) for part in re.findall(r"\d+", version)[:4])
    numbers += (0,) * (4 - len(numbers))
    strings = [
        versioninfo.StringStruct("CompanyName", "GridLens Contributors"),
        versioninfo.StringStruct("FileDescription", "GridLens"),
        versioninfo.StringStruct("FileVersion", version),
        versioninfo.StringStruct("LegalCopyright", "GPL-3.0-only"),
        versioninfo.StringStruct("ProductName", "GridLens"),
        versioninfo.StringStruct("ProductVersion", version),
    ]
    # US English, Unicode: the language and code page the strings are in.
    table = versioninfo.StringTable("040904B0", strings)
    translation = versioninfo.VarStruct("Translation", [1033, 1200])
    return versioninfo.VSVersionInfo(
        ffi=versioninfo.FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            versioninfo.StringFileInfo([table]),
            versioninfo.VarFileInfo([translation]),
        ],
    )


windows_options = {}
if WINDOWS:
    windows_options["version"] = _version_resource()
    if ICON.is_file():
        windows_options["icon"] = str(ICON)

a = Analysis(
    [str(project_root / "src" / "gridlens" / "main.py")],
    pathex=[str(project_root / "src")],
    binaries=binary_files,
    datas=[
        (
            str(project_root / "src" / "gridlens" / "resources"),
            "gridlens/resources",
        ),
        *metadata_files,
        *data_files,
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=[
        "matplotlib.tests",
        "pandas.tests",
        "py",
        "pytest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

# UPX breaks Qt's DLLs and makes antivirus tools flag the executables.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GridLens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    **windows_options,
)
executables = [exe]
if WINDOWS:
    # The MCP server, job workers, and the tool CLI talk over stdio, which a
    # windowed Windows executable does not reliably have. They run from this
    # console executable instead, which GridLens starts with no window.
    executables.append(EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="gridlens-cli",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        **windows_options,
    ))
coll = COLLECT(
    *executables,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GridLens",
)
