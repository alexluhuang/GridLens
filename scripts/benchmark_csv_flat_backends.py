"""Time the csv_flat result reduction on each aggregation backend.

Run it on a scratch copy of a run: every trial rebuilds the analysis cache
in the run's reports/ directory. Run it on an otherwise idle machine.

Each trial runs in a fresh process. It first evicts the run's input files
from the OS page cache with posix_fadvise, which needs no root, so each
trial reads the file from disk. Peak memory is the rise in system-wide used
memory (MemTotal - MemAvailable): on unified memory the GPU allocates from
the same pool, and RSS does not count those allocations.

GridLens uses CPU Dask only when cuDF and dask-cuDF are missing, so the
dask trial makes the GPU backends look unavailable. That is the only change
from production behaviour.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import threading
import time

BACKENDS = ("cudf", "dask_cudf", "dask", "python")
FACILITY_KEY = ("from_bus", "to_bus", "line_id", "section")
FACILITY_VALUES = (
    "max_utilization_pct",
    "max_utilization_contingency",
    "overload_count",
    "contingency_count",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backends", nargs="+", default=BACKENDS,
                        choices=BACKENDS)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--child", choices=BACKENDS, help=argparse.SUPPRESS)
    parser.add_argument("--trial", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.child:
        _run_trial(args.run, args.output, args.child, args.trial)
    else:
        _run_all(args)


def _run_all(args) -> None:
    records = []
    # Alternate backends within each round so drift affects all of them.
    for trial in range(1, args.trials + 1):
        for backend in args.backends:
            command = [
                sys.executable, __file__, "--run", str(args.run),
                "--output", str(args.output), "--child", backend,
                "--trial", str(trial),
            ]
            subprocess.run(command, check=True)
            path = args.output / f"trial_{backend}_{trial}.json"
            records.append(json.loads(path.read_text()))
            print(json.dumps(records[-1]), flush=True)
    summary = _summarize(records, args.output, args.backends)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def _run_trial(run: Path, output: Path, backend: str, trial: int) -> None:
    os.environ["GRIDLENS_CSV_FLAT_BACKEND"] = backend
    if backend == "dask":
        os.environ["GRIDLENS_ALLOW_CPU_DASK"] = "1"
    _evict_page_cache(run / "work")
    sampler = _Sampler()
    sampler.start()
    started = time.perf_counter()

    from gridlens.analysis import csv_flat
    from gridlens.analysis.interactive import (
        build_interactive_analysis_result,
    )
    from gridlens.analysis.utilization import (
        DEFAULT_UTILIZATION_BRANCH_OPTIONS,
    )

    imported = time.perf_counter()
    used, timing = _instrument(csv_flat, force_cpu_dask=backend == "dask")
    result = build_interactive_analysis_result(
        run, DEFAULT_UTILIZATION_BRANCH_OPTIONS, rebuild=True,
    )
    finished = time.perf_counter()
    sampler.stop()

    _write_facilities(
        output / f"facilities_{backend}_{trial}.csv",
        result.dataset.tables["pflow_mm"].rows,
    )
    flat = next((run / "work").glob("*_flat.csv"))
    record = {
        "backend": backend,
        "backend_used": used,
        "trial": trial,
        "flat_csv_bytes": flat.stat().st_size,
        "import_seconds": round(imported - started, 3),
        "aggregation_seconds": round(timing["aggregation"], 3),
        "build_seconds": round(finished - imported, 3),
        "peak_system_memory_rise_bytes": sampler.peak_rise,
        "peak_process_rss_bytes":
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "gpu_utilization_peak_pct": sampler.gpu_peak,
        "gpu_utilization_mean_pct": sampler.gpu_mean,
    }
    path = output / f"trial_{backend}_{trial}.json"
    path.write_text(json.dumps(record, indent=2))


def _instrument(csv_flat, force_cpu_dask: bool):
    """Record which backend ran and how long the reduction took."""
    used: list[str] = []
    timing = {"aggregation": 0.0}
    lazy_backend = csv_flat._lazy_backend
    streaming = csv_flat._parse_flat_results_streaming
    parse = csv_flat._parse_flat_results

    def recording_lazy_backend(*args, **kwargs):
        backend = lazy_backend(*args, **kwargs)
        used.append(backend.name)
        return backend

    def recording_streaming(*args, **kwargs):
        used.append("python")
        return streaming(*args, **kwargs)

    def timed_parse(*args, **kwargs):
        started = time.perf_counter()
        try:
            return parse(*args, **kwargs)
        finally:
            timing["aggregation"] += time.perf_counter() - started

    csv_flat._lazy_backend = recording_lazy_backend
    csv_flat._parse_flat_results_streaming = recording_streaming
    csv_flat._parse_flat_results = timed_parse
    if force_cpu_dask:
        csv_flat._gpu_backends_unavailable = lambda: True
    return used, timing


def _evict_page_cache(directory: Path) -> None:
    for path in directory.iterdir():
        if not path.is_file():
            continue
        fd = os.open(path, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)


def _used_memory_bytes() -> int:
    fields = {}
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            name, value = line.split(":", 1)
            fields[name] = int(value.split()[0]) * 1024
    return fields["MemTotal"] - fields["MemAvailable"]


class _Sampler(threading.Thread):
    """Sample system memory and GPU utilization every 100 ms."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.baseline = _used_memory_bytes()
        self.peak_rise = 0
        self.gpu_samples: list[int] = []
        self._done = threading.Event()
        self._gpu = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self._nvml = None

    def run(self) -> None:
        while not self._done.wait(0.1):
            rise = _used_memory_bytes() - self.baseline
            self.peak_rise = max(self.peak_rise, rise)
            if self._gpu is not None:
                rates = self._nvml.nvmlDeviceGetUtilizationRates(self._gpu)
                self.gpu_samples.append(rates.gpu)

    def stop(self) -> None:
        self._done.set()
        self.join()

    @property
    def gpu_peak(self) -> int | None:
        return max(self.gpu_samples) if self.gpu_samples else None

    @property
    def gpu_mean(self) -> float | None:
        if not self.gpu_samples:
            return None
        return round(statistics.fmean(self.gpu_samples), 1)


def _write_facilities(path: Path, rows) -> None:
    columns = FACILITY_KEY + FACILITY_VALUES
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(rows, key=_facility_key))


def _facility_key(row) -> tuple[str, ...]:
    return tuple(str(row.get(name) or "") for name in FACILITY_KEY)


def _read_facilities(path: Path) -> dict[tuple[str, ...], dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {_facility_key(row): row for row in csv.DictReader(handle)}


def _summarize(records, output: Path, backends) -> dict:
    reference = _read_facilities(output / f"facilities_{backends[-1]}_1.csv")
    summary = {"reference_backend": backends[-1], "backends": {}}
    for backend in backends:
        trials = [r for r in records if r["backend"] == backend]
        summary["backends"][backend] = {
            "backend_used": sorted({u for r in trials
                                    for u in r["backend_used"]}),
            "aggregation_seconds": _spread(trials, "aggregation_seconds"),
            "build_seconds": _spread(trials, "build_seconds"),
            "import_seconds": _spread(trials, "import_seconds"),
            "peak_system_memory_rise_gib": round(max(
                r["peak_system_memory_rise_bytes"] for r in trials
            ) / 1024**3, 2),
            "gpu_utilization_peak_pct": max(
                (r["gpu_utilization_peak_pct"] or 0) for r in trials
            ),
            "agreement": [
                _compare(reference, _read_facilities(
                    output / f"facilities_{backend}_{r['trial']}.csv"))
                for r in trials
            ],
        }
    return summary


def _spread(trials, field: str) -> dict:
    values = sorted(r[field] for r in trials)
    return {"median": statistics.median(values), "min": values[0],
            "max": values[-1], "all": values}


def _compare(reference, candidate) -> dict:
    shared = reference.keys() & candidate.keys()
    max_diff = 0.0
    mismatched = {name: 0 for name in FACILITY_VALUES[1:]}
    for key in shared:
        expected, actual = reference[key], candidate[key]
        max_diff = max(max_diff, abs(
            float(expected["max_utilization_pct"] or 0)
            - float(actual["max_utilization_pct"] or 0)
        ))
        for name in mismatched:
            mismatched[name] += expected[name] != actual[name]
    return {
        "facilities": len(candidate),
        "missing": len(reference.keys() - candidate.keys()),
        "extra": len(candidate.keys() - reference.keys()),
        "max_abs_diff_max_utilization_pct": max_diff,
        "mismatched": mismatched,
    }


if __name__ == "__main__":
    main()
