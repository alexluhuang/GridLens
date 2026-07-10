# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata
import importlib.util

project_root = Path.cwd()


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
for package in rapids_packages:
    datas, binaries, collected_hidden_imports = _collect_all(package)
    data_files += datas
    binary_files += binaries
    hidden_imports += collected_hidden_imports
for package in native_library_packages:
    binary_files += _collect_dynamic_libs(package, destdir=".")
for package in rapids_loader_library_packages:
    data_files += _collect_data_files(package, includes=["VERSION", "GIT_COMMIT"])
    binary_files += _collect_dynamic_libs(package)
binary_files += _collect_package_relative_files("numba_cuda", ["**/*.so"])
binary_files += _collect_package_relative_files("cuda", ["**/*.so"])
binary_files += _collect_library_globs("nvidia.cu13", ["lib/lib*.so*"])
binary_files += _collect_library_globs("nvidia.libnvcomp", ["lib64/lib*.so*"])
binary_files += _collect_library_globs("nvidia.nccl", ["lib/lib*.so*", "lib64/lib*.so*"])
for package in metadata_packages:
    metadata_files += _copy_metadata(package)

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
    runtime_hooks=[
        str(project_root / "packaging" / "pyinstaller" / "runtime_hooks" / "numba_cuda_redirector.py"),
    ],
    excludes=[
        "matplotlib.tests",
        "pandas.tests",
        "py",
        "pytest",
    ],
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
