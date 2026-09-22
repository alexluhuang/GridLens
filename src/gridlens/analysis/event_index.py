from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import time
from uuid import uuid4

from gridlens.analysis.progress import AnalysisProgress


INDEX_VERSION = "2026.09.22"
BUCKET_COUNT = 64


def find_flat_file(run_dir: Path) -> Path:
    from gridlens.analysis.csv_flat import _find_matching_csv, _is_flat_results_header

    path = _find_matching_csv(sorted((run_dir / "work").glob("*.csv")), _is_flat_results_header, preferred_terms=("flat", "result"))
    if path is None or path.is_symlink():
        raise ValueError("A regular csv_flat result file is required to build the event index.")
    return path


def build_event_index(run_dir: Path, *, progress=None, output_dir: Path | None = None, layout: str = "buckets") -> dict:
    """Stream CSV into bounded Parquet files; publish a manifest only after a complete build."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as csv
    import pyarrow.parquet as pq
    from gridlens.analysis.csv_flat import _column_lookup, _flat_lazy_columns, _header

    if layout not in ("unpartitioned", "sorted", "buckets"):
        raise ValueError("Unknown index layout.")
    source = find_flat_file(run_dir)
    source_stat = source.stat()
    destination = output_dir or run_dir / "reports/event_index"
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("The index directory must not be a symlink.")
    generation = uuid4().hex
    build_dir = destination / generation
    build_dir.mkdir()
    writers = {}
    started = time.monotonic()
    rows = 0
    mappings = _flat_lazy_columns(_column_lookup(_header(source)))
    types = {name: pa.string() for name in _header(source)}
    try:
        reader = csv.open_csv(source, read_options=csv.ReadOptions(block_size=16 * 1024 * 1024), convert_options=csv.ConvertOptions(column_types=types))
        for batch in reader:
            table = pa.Table.from_batches([batch])
            table = table.rename_columns([mappings.get(name, name) for name in table.column_names])
            if "section" not in table.column_names:
                table = table.append_column("section", pa.array([""] * len(table)))
            for name in ("line_id", "section"):
                value = pc.utf8_trim_whitespace(pc.fill_null(table[name], ""))
                value = pc.replace_substring_regex(value, pattern=r"^['\"]|['\"]$|\.0$", replacement="")
                table = table.set_column(table.schema.get_field_index(name), name, value)
            for name in ("event_idx", "from_bus", "to_bus", "loading_percent"):
                if name not in table.column_names:
                    raise ValueError(f"The event index requires {name}.")
                value = pc.cast(table[name], pa.float64())
                if name != "loading_percent":
                    value = pc.cast(value, pa.int64())
                table = table.set_column(table.schema.get_field_index(name), name, value)
            table = table.filter(pc.and_(pc.is_valid(table["event_idx"]), pc.is_finite(table["loading_percent"])))
            rows += len(table)
            if layout != "unpartitioned":
                table = table.take(pc.sort_indices(table, sort_keys=[("event_idx", "ascending")]))
            if layout == "buckets":
                buckets = pc.bit_wise_and(table["event_idx"], BUCKET_COUNT - 1)
                groups = [(int(key), table.filter(pc.equal(buckets, key))) for key in pc.unique(buckets).to_pylist()]
            else:
                groups = [(0, table)]
            for key, part in groups:
                if key not in writers:
                    writers[key] = pq.ParquetWriter(build_dir / f"bucket-{key:02d}.parquet", part.schema, compression="zstd")
                writers[key].write_table(part, row_group_size=65536)
            if progress:
                progress(AnalysisProgress("artifacts", f"Indexing contingency results: {rows:,} rows…"))
        for writer in writers.values():
            writer.close()
        writers.clear()
        if (source.stat().st_size, source.stat().st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
            raise ValueError("The flat result changed during indexing; rebuild the index.")
        manifest = {"version": INDEX_VERSION, "layout": layout, "generation": generation, "source": str(source.relative_to(run_dir)), "source_bytes": source_stat.st_size, "source_mtime_ns": source_stat.st_mtime_ns, "rows": rows, "seconds": round(time.monotonic() - started, 3), "parquet_bytes": sum(path.stat().st_size for path in build_dir.glob("*.parquet"))}
        temporary = destination / f"{generation}.json"
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary.replace(destination / "manifest.json")
        return manifest
    except BaseException:
        for writer in writers.values():
            writer.close()
        shutil.rmtree(build_dir)
        raise


def query_event_index(run_dir: Path, *, event_idx: int | None = None, branch: tuple | None = None, limit: int = 50, index_dir: Path | None = None) -> tuple[list[dict], int, list[Path]]:
    import pyarrow.dataset as ds
    from gridlens.agent.session import read_json, scoped_path

    if (event_idx is None) == (branch is None):
        raise ValueError("Select one event or one canonical branch key.")
    directory = index_dir or scoped_path(run_dir, "reports/event_index", directory=True)
    manifest_path = scoped_path(directory, "manifest.json")
    manifest = read_json(manifest_path)
    source = scoped_path(run_dir, manifest["source"])
    if manifest["version"] != INDEX_VERSION or (source.stat().st_size, source.stat().st_mtime_ns) != (manifest["source_bytes"], manifest["source_mtime_ns"]):
        raise ValueError("The event index is stale; build it again in the Agent tab.")
    generation = scoped_path(directory, manifest["generation"], directory=True)
    paths = sorted(generation.glob("*.parquet"))
    if manifest["layout"] == "buckets" and event_idx is not None:
        paths = [path for path in paths if path.name == f"bucket-{event_idx & (BUCKET_COUNT - 1):02d}.parquet"]
    for path in paths:
        scoped_path(generation, path.name)
    if not paths:
        return [], 0, [manifest_path, source]
    if event_idx is not None:
        predicate = ds.field("event_idx") == event_idx
    else:
        predicate = (ds.field("from_bus") == branch[0]) & (ds.field("to_bus") == branch[1]) & (ds.field("line_id") == branch[2]) & (ds.field("section") == branch[3])
    dataset = ds.dataset(paths, format="parquet")
    best, total = [], 0
    for batch in dataset.scanner(filter=predicate, batch_size=8192).to_batches():
        rows = batch.to_pylist()
        total += len(rows)
        best.extend(rows)
        best.sort(key=lambda row: (-abs(float(row["loading_percent"])), row["event_idx"], row["from_bus"], row["to_bus"], row["line_id"], row["section"]))
        del best[limit:]
    return best, total, [manifest_path, source, *paths]
