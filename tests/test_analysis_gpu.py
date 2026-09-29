"""A GPU is usable when the CUDA runtime says so, not when cuDF imports."""
from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest

from gridlens.analysis import gpu
from gridlens.analysis import gpu_pandas


@pytest.fixture
def uncached_device_check():
    """Let a test run the real device check, and leave no answer cached."""
    gpu.cuda_device_available.cache_clear()
    yield
    gpu.cuda_device_available.cache_clear()


def test_no_gpu_is_usable_without_cupy(
        monkeypatch, uncached_device_check) -> None:
    for name in ("cupy", "cupy.cuda", "cupy.cuda.runtime"):
        monkeypatch.setitem(sys.modules, name, None)

    assert gpu.cuda_device_available() is False
    assert gpu.device_memory() is None


def test_no_gpu_is_usable_when_no_device_is_visible() -> None:
    pytest.importorskip("cupy")
    environment = {**os.environ, "CUDA_VISIBLE_DEVICES": ""}
    code = "from gridlens.analysis import gpu; "
    code += "print(gpu.cuda_device_available())"

    completed = subprocess.run(
        [sys.executable, "-c", code], env=environment, capture_output=True,
        text=True, timeout=120, check=True)

    assert completed.stdout.strip() == "False"


def test_device_memory_reports_the_usable_gpu() -> None:
    if not gpu.cuda_device_available():
        pytest.skip("No CUDA device is usable on this machine")

    memory = gpu.device_memory()

    assert memory is not None
    assert memory.free_bytes > 0


def _fake_cudf(monkeypatch, install) -> None:
    """Install a stand-in for cudf.pandas whose install() calls install."""
    accelerator = types.SimpleNamespace(install=install)
    fake_cudf = types.SimpleNamespace(pandas=accelerator)
    monkeypatch.setitem(sys.modules, "cudf", fake_cudf)
    monkeypatch.setitem(sys.modules, "cudf.pandas", accelerator)


def test_get_pandas_is_unaccelerated_without_a_usable_gpu(
        monkeypatch) -> None:
    installs = []
    _fake_cudf(monkeypatch, lambda: installs.append(True))
    monkeypatch.setattr(gpu, "cuda_device_available", lambda: False)

    pd = gpu_pandas.get_pandas()

    assert pd.__name__ == "pandas"
    assert installs == []


def test_get_pandas_warns_and_uses_pandas_if_the_accelerator_fails(
        monkeypatch) -> None:
    def fail() -> None:
        raise RuntimeError("driver too old")

    _fake_cudf(monkeypatch, fail)
    monkeypatch.setattr(gpu, "cuda_device_available", lambda: True)

    with pytest.warns(RuntimeWarning, match="driver too old"):
        pd = gpu_pandas.get_pandas()

    assert pd.__name__ == "pandas"
