"""The drill-down index: every row of a run's flat result, in Parquet, for per-contingency questions.

`build_event_index` streams the multi-gigabyte csv_flat result into 64 Parquet files bucketed by event,
with the key, loading, flow, voltage, and angle columns stored as numbers. The two query functions read
those files under the same checks: `scan_cases` ranks the rows (cases) that pass a set of qualifiers by
one metric, and `group_cases` computes a statistic of a metric over every such row per group. Both read
only the columns they need, prune buckets when the qualifiers name events, and hold the best rows or the
running totals of each group rather than the rows themselves.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from uuid import uuid4

from gridlens.analysis.distribution_stats import ORDER_STATISTICS, GroupAccumulator
from gridlens.analysis.progress import AnalysisProgress


# 2026.09.24 stores flows, voltages, and angles as numbers; earlier indexes hold them as text.
INDEX_VERSION = "2026.09.24"
BUCKET_COUNT = 64
KEY_COLUMNS = ("event_idx", "contingency", "from_bus", "to_bus", "line_id", "section")
NUMERIC_COLUMNS = ("p_from_mw", "q_from_mvar", "mva_from", "rate_mva", "viol", "v_from_pu", "v_to_pu", "ang_from_deg", "ang_to_deg")
# Case metrics: units, what the value means, and the index columns it is computed from.
CASE_METRICS = {
    "loading_percent": ("%", "absolute loading of the facility in this case, as GridPACK reports it against rate_mva", ("loading_percent",)),
    "mva_from": ("MVA", "apparent power at the from end", ("mva_from",)),
    "p_from_mw": ("MW", "real power at the from end; the sign gives the direction", ("p_from_mw",)),
    "q_from_mvar": ("Mvar", "reactive power at the from end; the sign gives the direction", ("q_from_mvar",)),
    "rate_mva": ("MVA", "the rating this case's loading is computed against", ("rate_mva",)),
    "v_from_pu": ("pu", "voltage magnitude at the from end", ("v_from_pu",)),
    "v_to_pu": ("pu", "voltage magnitude at the to end", ("v_to_pu",)),
    "min_voltage_pu": ("pu", "the lower of the two end voltage magnitudes", ("v_from_pu", "v_to_pu")),
    "ang_from_deg": ("degrees", "voltage angle at the from end", ("ang_from_deg",)),
    "ang_to_deg": ("degrees", "voltage angle at the to end", ("ang_to_deg",)),
    "angle_difference_deg": ("degrees", "absolute difference between the two end voltage angles", ("ang_from_deg", "ang_to_deg")),
}
# Rows held at once when a caller asks for every matching case, or for an order statistic of them.
MAX_CASE_ROWS = 1_000_000


class IndexStale(ValueError):
    """The index is of another version, or its flat result changed after it was built."""


class IndexColumnsMissing(LookupError):
    """The flat result the index was built from has no column a query needs."""


class TooManyCases(ValueError):
    """A query would hold more matching cases than MAX_CASE_ROWS."""


def find_flat_file(run_dir: Path) -> Path:
    from gridlens.analysis.csv_flat import _find_matching_csv, _is_flat_results_header

    path = _find_matching_csv(sorted((run_dir / "work").glob("*.csv")), _is_flat_results_header, preferred_terms=("flat", "result"))
    if path is None or path.is_symlink():
        raise ValueError("A regular csv_flat result file is required to build the event index.")
    return path


def _numbers(pc, pa, values):
    """Cast a text column to float64, reading an empty or unparseable cell as missing."""
    text = pc.utf8_trim_whitespace(values)
    valid = pc.match_substring_regex(text, pattern=r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
    return pc.cast(pc.if_else(valid, text, pa.scalar(None, pa.string())), pa.float64())


def build_event_index(run_dir: Path, *, progress=None, output_dir: Path | None = None, layout: str = "buckets") -> dict:
    """Stream CSV into bounded Parquet files; publish a manifest only after a complete build."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as csv
    import pyarrow.parquet as pq
    from gridlens.analysis.branch_keys import canonical_branch_arrow
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
                value = canonical_branch_arrow(table[name])
                table = table.set_column(table.schema.get_field_index(name), name, value)
            for name in ("event_idx", "from_bus", "to_bus", "loading_percent"):
                if name not in table.column_names:
                    raise ValueError(f"The event index requires {name}.")
                value = pc.cast(table[name], pa.float64())
                if name != "loading_percent":
                    value = pc.cast(value, pa.int64())
                table = table.set_column(table.schema.get_field_index(name), name, value)
            for name in NUMERIC_COLUMNS:
                if name in table.column_names:
                    table = table.set_column(table.schema.get_field_index(name), name, _numbers(pc, pa, table[name]))
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


def open_event_index(run_dir: Path, *, events: set[int] | None = None, index_dir: Path | None = None):
    """Return a Parquet dataset over a run's current index, its manifest, and the files it reads.

    Only the buckets holding events are read when events is given. Raises ValueError for an index that
    is stale or of another version, and AgentError from `scoped_path` for any path that escapes the run.
    """
    import pyarrow.dataset as ds
    from gridlens.agent.session import read_json, scoped_path

    directory = index_dir or scoped_path(run_dir, "reports/event_index", directory=True)
    manifest_path = scoped_path(directory, "manifest.json")
    manifest = read_json(manifest_path)
    source = scoped_path(run_dir, manifest["source"])
    if manifest["version"] != INDEX_VERSION or (source.stat().st_size, source.stat().st_mtime_ns) != (manifest["source_bytes"], manifest["source_mtime_ns"]):
        raise IndexStale("The event index is stale; build it again in the Agent tab.")
    generation = scoped_path(directory, manifest["generation"], directory=True)
    paths = sorted(generation.glob("*.parquet"))
    if manifest["layout"] == "buckets" and events is not None:
        wanted = {f"bucket-{event & (BUCKET_COUNT - 1):02d}.parquet" for event in events}
        paths = [path for path in paths if path.name in wanted]
    for path in paths:
        scoped_path(generation, path.name)
    dataset = ds.dataset(paths, format="parquet") if paths else None
    return dataset, manifest, [manifest_path, source, *paths]


def _case_values(pc, table, metric: str):
    """Compute one case metric for every row of an Arrow table."""
    if metric == "loading_percent":
        return pc.abs(table["loading_percent"])
    if metric == "min_voltage_pu":
        return pc.min_element_wise(table["v_from_pu"], table["v_to_pu"])
    if metric == "angle_difference_deg":
        return pc.abs(pc.subtract(table["ang_from_deg"], table["ang_to_deg"]))
    return pc.cast(table[metric], "float64")


def _condition_mask(pc, pa, table, column: str, op: str, value):
    """Return the rows of table that meet one numeric qualifier on a case metric or viol."""
    values = _case_values(pc, table, column) if column in CASE_METRICS else pc.cast(table[column], "float64")
    if op == "in":
        return pc.is_in(values, value_set=pa.array([float(item) for item in value], pa.float64()))
    compare = {"==": pc.equal, "!=": pc.not_equal, "<": pc.less, "<=": pc.less_equal, ">": pc.greater, ">=": pc.greater_equal}[op]
    return pc.fill_null(compare(values, float(value)), False)


def case_columns(metric: str, conditions, extra: tuple[str, ...] = ()) -> list[str]:
    """Return the index columns a scan needs for its keys, metric, qualifiers, and extra fields."""
    needed = list(KEY_COLUMNS)
    for name in [metric, *(column for column, _, _ in conditions), *extra]:
        for column in (CASE_METRICS[name][2] if name in CASE_METRICS else (name,)):
            if column not in needed:
                needed.append(column)
    return needed


def _filtered_batches(dataset, metric: str, *, events, keys, conditions, extra=()):
    """Yield Arrow tables of the rows that pass every qualifier, each with its metric in a value column."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.dataset as ds

    columns = case_columns(metric, conditions, extra)
    missing = [name for name in columns if name not in dataset.schema.names]
    if missing:
        raise IndexColumnsMissing(", ".join(missing))
    predicate = ds.field("event_idx").isin(sorted(events)) if events is not None else None
    key_set = pa.array(sorted(keys), pa.string()) if keys is not None else None
    for batch in dataset.scanner(columns=columns, filter=predicate, batch_size=65536).to_batches():
        table = pa.Table.from_batches([batch])
        if key_set is not None:
            key = pc.binary_join_element_wise(pc.cast(table["from_bus"], pa.string()), pc.cast(table["to_bus"], pa.string()), table["line_id"], table["section"], "|")
            table = table.filter(pc.is_in(key, value_set=key_set))
        for column, op, value in conditions:
            if len(table):
                table = table.filter(_condition_mask(pc, pa, table, column, op, value))
        if not len(table):
            continue
        table = table.append_column("value", _case_values(pc, table, metric))
        table = table.filter(pc.is_valid(table["value"]))
        if len(table):
            yield table


def case_key(from_bus: object, to_bus: object, line_id: object, section: object) -> str:
    """Return the text key the index scans use for one facility."""
    return f"{from_bus}|{to_bus}|{line_id}|{section}"


def scan_cases(run_dir: Path, *, metric: str, descending: bool = True, limit: int = 10, events: set[int] | None = None, keys: set[str] | None = None, conditions=(), extra: tuple[str, ...] = (), index_dir: Path | None = None) -> tuple[list[dict], int, list[Path]]:
    """Rank the index rows that pass the qualifiers by metric; return the first limit rows (0 for all), their count, and the files read.

    keys are `case_key` strings of the facilities to keep; conditions are numeric qualifiers on case
    metrics or viol. Ties keep event and full-key order, so parallel circuits and sections stay apart.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    dataset, _, paths = open_event_index(run_dir, events=events, index_dir=index_dir)
    if dataset is None or (events is not None and not events) or (keys is not None and not keys):
        return [], 0, paths
    order = "descending" if descending else "ascending"
    sort_keys = [("value", order), ("event_idx", "ascending"), ("from_bus", "ascending"), ("to_bus", "ascending"), ("line_id", "ascending"), ("section", "ascending")]
    best, total = None, 0
    for table in _filtered_batches(dataset, metric, events=events, keys=keys, conditions=conditions, extra=extra):
        total += len(table)
        best = table if best is None else pa.concat_tables([best, table])
        if limit:
            best = best.take(pc.sort_indices(best, sort_keys=sort_keys)[:limit])
        elif len(best) > MAX_CASE_ROWS:
            raise TooManyCases(f"More than {MAX_CASE_ROWS:,} cases match; add qualifiers, or ask for fewer with magnitude.")
    if best is None:
        return [], 0, paths
    best = best.take(pc.sort_indices(best, sort_keys=sort_keys))
    return best.to_pylist(), total, paths


def group_cases(run_dir: Path, *, metric: str, statistic: str, by: str, labels: dict, events: set[int] | None = None, keys: set[str] | None = None, conditions=(), index_dir: Path | None = None) -> tuple[dict[str, GroupAccumulator], int, list[Path]]:
    """Compute statistic of metric over every qualifying index row per group; return the groups, rows used, and files read.

    by is "event" or "facility": each row's event_idx, or its `case_key`, is looked up in labels, which
    gives the groups it belongs to; a facility joining two areas counts in both. Rows with no label go
    to "unknown". Running totals are merged batch by batch, so only median and iqr hold values.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    dataset, _, paths = open_event_index(run_dir, events=events, index_dir=index_dir)
    groups: dict[str, GroupAccumulator] = {}
    if dataset is None or (events is not None and not events) or (keys is not None and not keys):
        return groups, 0, paths
    used = 0
    for table in _filtered_batches(dataset, metric, events=events, keys=keys, conditions=conditions):
        used += len(table)
        if statistic in ORDER_STATISTICS and used > MAX_CASE_ROWS:
            raise TooManyCases(f"A {statistic} needs every value and more than {MAX_CASE_ROWS:,} cases match; add qualifiers, or use a statistic kept as running totals, such as mean.")
        if by == "event":
            group_column = table["event_idx"]
        else:
            group_column = pc.binary_join_element_wise(pc.cast(table["from_bus"], pa.string()), pc.cast(table["to_bus"], pa.string()), table["line_id"], table["section"], "|")
        values = table["value"]
        parts = pa.table({"group": group_column, "value": values, "square": pc.multiply(values, values)})
        aggregates = [("value", "count"), ("value", "sum"), ("value", "min"), ("value", "max"), ("square", "sum")]
        if statistic in ORDER_STATISTICS:
            aggregates.append(("value", "list"))
        for part in parts.group_by("group").aggregate(aggregates).to_pylist():
            for label in labels.get(part["group"], ["unknown"]):
                if label not in groups:
                    groups[label] = GroupAccumulator(statistic)
                groups[label].merge(part["value_count"], part["value_sum"], part["square_sum"], part["value_min"], part["value_max"], part.get("value_list") or ())
    return groups, used, paths


def query_event_index(run_dir: Path, *, event_idx: int | None = None, branch: tuple | None = None, limit: int = 50, index_dir: Path | None = None) -> tuple[list[dict], int, list[Path]]:
    """Return the highest-loading index rows for one event or one branch key, their total count, and the files read.

    A thin form of scan_cases for the event and branch drill-down tools; limit=0 keeps every matching row.
    """
    if (event_idx is None) == (branch is None):
        raise ValueError("Select one event or one canonical branch key.")
    dataset, _, _ = open_event_index(run_dir, index_dir=index_dir)
    extra = tuple(name for name in NUMERIC_COLUMNS if dataset is not None and name in dataset.schema.names)
    events = {event_idx} if event_idx is not None else None
    keys = {case_key(*branch)} if branch is not None else None
    rows, total, paths = scan_cases(run_dir, metric="loading_percent", limit=limit, events=events, keys=keys, extra=extra, index_dir=index_dir)
    for row in rows:
        row.pop("value", None)
    return rows, total, paths
