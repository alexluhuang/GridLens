"""Whether this machine's GPU can run the analysis, and how much memory it has.

Importing cuDF does not show that a GPU is usable. cuDF imports with only a
warning when no device is visible or when the driver is older than its CUDA
version needs, and then fails on the first operation. So the analysis asks the
CUDA runtime directly, through CuPy, which cuDF installs.

A GPU may share the host's memory, as DGX Spark's GB10 does, or have its own,
as Grace Hopper and PCIe GPUs do. `device_memory` reports which, so a caller
can size its work to the memory the GPU can actually use.
"""
from __future__ import annotations

from dataclasses import dataclass
import functools


@dataclass(frozen=True)
class DeviceMemory:
    """The first CUDA device's free memory, and whether it is host memory."""

    free_bytes: int
    integrated: bool


@functools.cache
def cuda_device_available() -> bool:
    """Return True when the CUDA runtime reports at least one usable device.

    The answer is cached for the life of the process, because the devices and
    the driver do not change while it runs.
    """
    try:
        from cupy.cuda import runtime

        return runtime.getDeviceCount() > 0
    except Exception:
        # No CuPy, no driver, a driver too old for this CUDA version, or no
        # visible device: each means the GPU backends cannot run.
        return False


def device_memory() -> DeviceMemory | None:
    """Return the first device's free memory, or None when no GPU is usable."""
    if not cuda_device_available():
        return None
    try:
        import cupy
        from cupy.cuda import runtime

        free_bytes, _total_bytes = cupy.cuda.Device(0).mem_info
        integrated = bool(runtime.getDeviceProperties(0).get("integrated"))
    except Exception:
        return None
    return DeviceMemory(int(free_bytes), integrated)
