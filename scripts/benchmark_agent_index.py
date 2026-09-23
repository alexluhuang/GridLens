"""Compare supported index layouts without changing the source run.

Run each layout in a fresh process for independent peak RSS measurements.
The first query is an OS-cache-dependent first read, not a privileged cache flush.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import time

from gridlens.analysis.event_index import build_event_index, case_key, scan_cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--layout", choices=("unpartitioned", "sorted", "buckets"), required=True)
    parser.add_argument("--event", type=int, default=1)
    args = parser.parse_args()
    last_report = 0.0

    def progress(update):
        nonlocal last_report
        if time.monotonic() - last_report > 20:
            print(update.detail, flush=True)
            last_report = time.monotonic()

    manifest = build_event_index(args.run, output_dir=args.output, layout=args.layout, progress=progress)
    record = {**manifest, "disk_ratio": manifest["parquet_bytes"] / manifest["source_bytes"], "gpu_peak_bytes": 0, "backend": "PyArrow CPU"}
    query_times = []
    for _ in range(2):
        started = time.monotonic()
        rows, total, _ = scan_cases(args.run, metric="loading_percent", limit=50, events={args.event}, index_dir=args.output)
        query_times.append(round(time.monotonic() - started, 4))
    record.update(event_query_seconds=query_times, event_matching_rows=total)
    if rows:
        key = tuple(rows[0][name] for name in ("from_bus", "to_bus", "line_id", "section"))
        started = time.monotonic()
        _, total, _ = scan_cases(args.run, metric="loading_percent", limit=50, keys={case_key(*key)}, index_dir=args.output)
        record.update(branch_query_seconds=round(time.monotonic() - started, 4), branch_matching_rows=total)
    record["peak_host_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    record["cache_note"] = "First/warm reads; OS cache was not forcibly flushed. Zero GPU memory because this conversion uses CPU PyArrow."
    # No project name, absolute path, bus ID, or loading value in the shareable measurements.
    for key in ("generation", "source", "source_mtime_ns"):
        record.pop(key, None)
    (args.output / "benchmark.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
