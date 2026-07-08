from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_debian_control_downloads_docker_and_qt_runtime_dependencies() -> None:
    control = _read("packaging/deb/control")

    assert "docker.io | docker-ce" in control
    assert "libxcb-cursor0" in control
    assert "libxkbcommon-x11-0" in control


def test_debian_postinst_enables_docker_and_configures_installing_user() -> None:
    postinst = _read("packaging/deb/postinst")

    assert "systemctl enable --now docker" in postinst
    assert 'INSTALL_USER="${SUDO_USER:-}"' in postinst
    assert 'adduser "$INSTALL_USER" docker' in postinst


def test_debian_build_script_bundles_full_python_stack() -> None:
    build_script = _read("packaging/deb/build_deb.sh")

    assert 'pip install -e "${ROOT_DIR}[dev,analysis]"' in build_script
    assert "dpkg --print-architecture" in build_script
    assert 'dist/gridlens_${VERSION}_${ARCH}.deb' in build_script


def test_pyinstaller_spec_collects_analysis_packages() -> None:
    spec = _read("packaging/pyinstaller/gridlens.spec")

    for package in ("matplotlib", "pandas", "dask", "distributed", "pyarrow", "cudf", "dask_cudf"):
        assert package in spec


def test_analysis_requirements_include_rapids_stack() -> None:
    requirements = _read("requirements-analysis.txt")

    for package in ("cudf-cu13", "dask-cudf-cu13", "dask-cuda", "cupy-cuda13x", "cuda-toolkit", "nvidia-nccl-cu13"):
        assert package in requirements
