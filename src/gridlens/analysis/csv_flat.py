from __future__ import annotations

from contextlib import contextmanager, suppress
import csv
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Callable, Iterable

from gridlens.analysis.parser_models import ParsedTable
from gridlens.analysis.progress import PHASE_PARSE, ProgressCallback, report
from gridlens.analysis.raw_parsers import AREA_METADATA_COLUMNS, BRANCH_METADATA_COLUMNS, BUS_METADATA_COLUMNS
from gridlens.analysis.utilization import NONTRANSFORMER_BRANCH


CSV_FLAT_PREVIEW_LIMIT = 200
CSV_FLAT_RESULTS_TABLE = "csv_flat_results"
CSV_FLAT_CONVERGENCE_TABLE = "csv_flat_convergence"
CSV_FLAT_BUS_TABLE = "csv_flat_bus_metadata"
CSV_FLAT_BRANCH_TABLE = "csv_flat_branch_metadata"
CSV_FLAT_DEFAULT_BACKEND = "auto"
CSV_FLAT_DEFAULT_BLOCKSIZE = "256MB"
CSV_FLAT_DEFAULT_SCHEDULER = "threads"
CSV_FLAT_MEMORY_TARGET = "160GB"
CSV_FLAT_DEFAULT_CLUSTER = "auto"
CSV_FLAT_DEFAULT_DASK_TEMP_DIR = "/tmp/gridlens-dask"
CSV_FLAT_DEFAULT_DEVICE_MEMORY_LIMIT = "auto"
CSV_FLAT_ALLOW_CPU_DASK_ENV = "GRIDLENS_ALLOW_CPU_DASK"
CSV_FLAT_CUDF_MEMORY_FRACTION = 0.75
CSV_FLAT_MEMORY_HEADROOM = 0.95
CSV_FLAT_MIN_BLOCKSIZE_BYTES = 64 * 1024**2

_EVENT_ALIASES = ("event_idx", "event_index", "contingency_index")
_CONTINGENCY_ALIASES = ("contingency", "contingency_name", "event")
_FROM_BUS_ALIASES = ("from_bus", "frombus", "i_bus", "ibus")
_TO_BUS_ALIASES = ("to_bus", "tobus", "j_bus", "jbus")
_CIRCUIT_ALIASES = ("circuit_id", "circuit", "ckt", "line_id")
_SECTION_ALIASES = ("section", "section_id")
_LOADING_ALIASES = ("loading_percent", "loading_pct", "loading", "utilization_percent", "utilization_pct")

_FLAT_RESULT_COLUMNS = [
    "event_idx",
    "contingency",
    "from_bus",
    "to_bus",
    "line_id",
    "section",
    "p_from_mw",
    "q_from_mvar",
    "mva_from",
    "rate_mva",
    "loading_percent",
    "viol",
    "v_from_pu",
    "v_to_pu",
    "ang_from_deg",
    "ang_to_deg",
]
_PFLOW_COLUMNS = [
    "row_index",
    "from_bus",
    "to_bus",
    "line_id",
    "section",
    "average",
    "rms_average",
    "rms_base",
    "average_utilization_pct",
    "contingency_count",
    "utilization_source",
]
_PFLOW_MM_COLUMNS = [
    "row_index",
    "from_bus",
    "to_bus",
    "line_id",
    "section",
    "base_value",
    "min_value",
    "max_value",
    "min_deviation",
    "max_deviation",
    "min_allowable",
    "max_allowable",
    "min_contingency",
    "max_contingency",
    "base_utilization_pct",
    "mean_utilization_pct",
    "max_utilization_pct",
    "max_utilization_contingency",
    "max_contingency_label",
    "contingency_count",
    "overload_count",
    "utilization_source",
]
_SUCCESS_COLUMNS = ["contingency_index", "success", "violation", "isolated_warning", "raw_line"]
_CONVERGENCE_COLUMNS = [
    "event_idx",
    "contingency",
    "type",
    "converged",
    "iterations",
    "final_tolerance",
    "max_p_bus",
    "max_p_mismatch",
    "max_q_bus",
    "max_q_mismatch",
    "status_code",
]
_BUS_COLUMNS = [
    *BUS_METADATA_COLUMNS,
    "area_name",
    "zone_name",
    "owner_name",
]
_BRANCH_COLUMNS = [
    *BRANCH_METADATA_COLUMNS,
    "section",
    "rate_mva",
    "source_file",
]


@dataclass(slots=True)
class ConversionResult:
    parquet_path: Path | None
    note: str = ""
    backend: str = ""

    @property
    def ok(self) -> bool:
        return self.parquet_path is not None


@dataclass(slots=True)
class _LazyBackend:
    name: str
    module: object


@dataclass(slots=True)
class _DaskRuntime:
    compute_kwargs: dict[str, object]
    note: str


@dataclass(slots=True)
class _ExtremeLabels:
    min_event_idx: object = ""
    max_event_idx: object = ""
    max_abs_event_idx: object = ""
    max_abs_contingency: str = ""


@dataclass(slots=True)
class _BranchAggregate:
    from_bus: int | None
    to_bus: int | None
    line_id: str
    section: str
    row_index: int
    count: int = 0
    overload_count: int = 0
    sum_loading: float = 0.0
    min_loading: float | None = None
    max_loading: float | None = None
    max_abs_loading: float | None = None
    base_loading: float | None = None
    min_event_idx: object = ""
    max_event_idx: object = ""
    max_abs_event_idx: object = ""
    max_abs_contingency: str = ""
    rate_mva: float | None = None

    def update(self, row: dict[str, object]) -> None:
        loading = _float_value(row.get("loading_percent"))
        if loading is None:
            return

        self.count += 1
        self.sum_loading += loading
        if _is_base_case(row.get("event_idx"), row.get("contingency")):
            self.base_loading = loading
        if _is_truthy(row.get("viol")) or loading >= 100.0:
            self.overload_count += 1

        if self.min_loading is None or loading < self.min_loading:
            self.min_loading = loading
            self.min_event_idx = row.get("event_idx", "")
        if self.max_loading is None or loading > self.max_loading:
            self.max_loading = loading
            self.max_event_idx = row.get("event_idx", "")

        abs_loading = abs(loading)
        if self.max_abs_loading is None or abs_loading > self.max_abs_loading:
            self.max_abs_loading = abs_loading
            self.max_abs_event_idx = row.get("event_idx", "")
            self.max_abs_contingency = str(row.get("contingency") or "")

        if self.rate_mva is None:
            self.rate_mva = _float_value(row.get("rate_mva"))

    @property
    def mean_loading(self) -> float | None:
        if not self.count:
            return None
        return self.sum_loading / self.count


def parse_csv_flat_outputs(run_dir: str | Path, progress: ProgressCallback | None = None) -> dict[str, ParsedTable]:
    """Parse GridPACK ca-scalability-v2 csv_flat outputs into GridLens logical tables."""

    work_dir = Path(run_dir) / "work"
    if not work_dir.exists():
        return {}

    csv_files = sorted(path for path in work_dir.rglob("*.csv") if path.is_file())
    if not csv_files:
        return {}

    flat_path = _find_matching_csv(csv_files, _is_flat_results_header, preferred_terms=("flat", "result"))
    convergence_path = _find_matching_csv(csv_files, _is_convergence_header, preferred_terms=("convergence",))
    bus_path = _find_matching_csv(csv_files, _is_bus_metadata_header, preferred_terms=("bus",))
    backend_decision_path = _largest_existing_path(path for path in (flat_path, convergence_path, bus_path) if path)

    tables: dict[str, ParsedTable] = {}
    if flat_path:
        tables.update(_parse_flat_results(flat_path, backend_decision_path, progress=progress))
    if convergence_path:
        convergence, success = _parse_convergence(convergence_path)
        tables[CSV_FLAT_CONVERGENCE_TABLE] = convergence
        tables["success"] = success
    if bus_path:
        bus_metadata, area_metadata = _parse_bus_metadata(bus_path)
        tables[CSV_FLAT_BUS_TABLE] = ParsedTable(
            CSV_FLAT_BUS_TABLE,
            bus_metadata.source_file,
            list(bus_metadata.columns),
            list(bus_metadata.rows),
            list(bus_metadata.notes),
        )
        tables["bus_metadata"] = bus_metadata
        tables["area_metadata"] = area_metadata
    return tables


def parse_csv_flat_success(run_dir: str | Path) -> ParsedTable | None:
    """Parse only the ca-scalability-v2 convergence CSV into the legacy success shape."""

    work_dir = Path(run_dir) / "work"
    if not work_dir.exists():
        return None
    csv_files = sorted(path for path in work_dir.rglob("*.csv") if path.is_file())
    convergence_path = _find_matching_csv(csv_files, _is_convergence_header, preferred_terms=("convergence",))
    if not convergence_path:
        return None
    return _parse_convergence(convergence_path)[1]


def cpu_dask_fallback_warning(run_dir: str | Path) -> str:
    """Return the warning text required before the UI allows CPU Dask fallback."""

    if _requested_backend() not in {"auto", "dask"}:
        return ""
    work_dir = Path(run_dir) / "work"
    if not work_dir.exists():
        return ""
    csv_files = sorted(path for path in work_dir.rglob("*.csv") if path.is_file())
    if not csv_files:
        return ""
    flat_path = _find_matching_csv(csv_files, _is_flat_results_header, preferred_terms=("flat", "result"))
    if not flat_path:
        return ""
    if not _gpu_backends_unavailable() or not _backend_importable("dask"):
        return ""
    largest = _largest_existing_path(csv_files) or flat_path
    size = _format_file_size(largest.stat().st_size)
    return (
        "RAPIDS cuDF and dask-cuDF are not available in this Python environment, so GridLens "
        f"will use CPU Dask for CSV-flat graph analysis. Largest CSV detected: {largest.name} ({size}). "
        "GPU acceleration will not be used for this analysis run."
    )


def merge_csv_flat_branch_metadata(raw_table: ParsedTable, csv_flat_table: ParsedTable | None) -> ParsedTable:
    """Overlay RAW metadata on csv_flat branch keys while preserving section-level rows."""

    if not csv_flat_table or not csv_flat_table.rows:
        return raw_table

    raw_by_key = {_metadata_key(row): row for row in raw_table.rows}
    merged_rows: list[dict[str, object]] = []
    for csv_row in csv_flat_table.rows:
        merged = dict(csv_row)
        raw_row = raw_by_key.get(_metadata_key(csv_row))
        if raw_row:
            for key, value in raw_row.items():
                if key in {"from_bus", "to_bus", "line_id", "section"}:
                    continue
                if value not in (None, ""):
                    merged[key] = value
        merged_rows.append(merged)

    columns = _dedupe([*csv_flat_table.columns, *raw_table.columns, "section"])
    return ParsedTable(
        "branch_metadata",
        csv_flat_table.source_file,
        columns,
        merged_rows,
        notes=[
            "Branch metadata was keyed from csv_flat monitored facilities; RAW metadata was merged where available.",
            *csv_flat_table.notes,
            *raw_table.notes,
        ],
    )


def ensure_csv_flat_parquet(run_dir: str | Path, tables: dict[str, ParsedTable]) -> dict[str, dict[str, str]]:
    """Convert the large csv_flat branch result file to parquet when Dask/PyArrow are installed."""

    table = tables.get(CSV_FLAT_RESULTS_TABLE)
    if not table or not table.source_file:
        return {}

    run_path = Path(run_dir).expanduser().resolve()
    source_path = _find_work_file(run_path, table.source_file)
    if not source_path:
        return {}

    parquet_dir = run_path / "reports" / "parquet" / source_path.stem
    result = convert_csv_to_parquet(source_path, parquet_dir)
    if result.ok and result.parquet_path:
        table.notes.append(f"Full csv_flat results were converted to parquet: {result.parquet_path}")
        return {CSV_FLAT_RESULTS_TABLE: {"parquet": str(result.parquet_path)}}
    if result.note:
        table.notes.append(result.note)
    return {}


def convert_csv_to_parquet(csv_path: str | Path, output_dir: str | Path, blocksize: str = "") -> ConversionResult:
    """Convert csv_flat output to parquet, preferring RAPIDS dask-cudf when available."""

    source = Path(csv_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    blocksize = blocksize or _dask_blocksize(source)
    if destination.exists() and any(destination.rglob("*.parquet")):
        return ConversionResult(destination, backend="existing")

    try:
        backend = _lazy_backend(source)
    except Exception as exc:  # pragma: no cover - depends on optional local install.
        return ConversionResult(
            None,
            (
                "csv_flat parquet conversion was skipped because Dask/RAPIDS analysis "
                f"dependencies are not installed: {exc}"
            ),
        )

    try:
        destination.mkdir(parents=True, exist_ok=True)
        if backend.name == "cudf":
            data = _read_eager_csv(backend, source)
            data.to_parquet(destination / "part.0.parquet", compression="snappy", index=False)
        else:
            with _dask_runtime(backend) as runtime:
                data = _read_lazy_csv(backend, source, blocksize=blocksize)
                with _dask_scheduler_config(runtime):
                    data.to_parquet(destination, engine="pyarrow", compression="snappy", write_index=False)
    except Exception as exc:  # pragma: no cover - depends on local parquet stack and filesystem state.
        return ConversionResult(None, f"csv_flat parquet conversion failed for {source.name}: {exc}", backend.name)
    return ConversionResult(destination, backend=backend.name)


def _parse_flat_results(
    path: Path,
    backend_decision_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, ParsedTable]:
    lookup = _column_lookup(_header(path))
    total_estimate = _estimate_total_rows(path) if progress is not None else None
    accelerated, fallback_note = _parse_flat_results_accelerated(
        path, lookup, backend_decision_path or path, progress=progress, total_estimate=total_estimate
    )
    if accelerated:
        return accelerated

    return _parse_flat_results_streaming(
        path, lookup, fallback_note, progress=progress, total_estimate=total_estimate
    )


def _parse_flat_results_streaming(
    path: Path,
    lookup: dict[str, str],
    fallback_note: str = "",
    progress: ProgressCallback | None = None,
    total_estimate: int | None = None,
) -> dict[str, ParsedTable]:
    aggregates: dict[tuple[object, object, str, str], _BranchAggregate] = {}
    preview_rows: list[dict[str, object]] = []
    rejected = 0

    total_text = _format_rows(total_estimate)
    seen = 0
    for raw_row in _dict_rows(path):
        seen += 1
        if progress is not None and seen % _PROGRESS_ROW_INTERVAL == 0:
            fraction = min(0.99, seen / total_estimate) if total_estimate else None
            report(
                progress,
                PHASE_PARSE,
                f"Parsing GridPACK contingency outputs - row {seen:,} of ~{total_text} rows...",
                fraction,
            )
        row = _normalize_flat_result_row(raw_row, lookup)
        if row is None:
            rejected += 1
            continue
        if len(preview_rows) < CSV_FLAT_PREVIEW_LIMIT:
            preview_rows.append(row)

        key = (
            row.get("from_bus"),
            row.get("to_bus"),
            str(row.get("line_id") or ""),
            str(row.get("section") or ""),
        )
        aggregate = aggregates.get(key)
        if aggregate is None:
            aggregate = _BranchAggregate(
                from_bus=row.get("from_bus") if isinstance(row.get("from_bus"), int) else None,
                to_bus=row.get("to_bus") if isinstance(row.get("to_bus"), int) else None,
                line_id=str(row.get("line_id") or ""),
                section=str(row.get("section") or ""),
                row_index=len(aggregates) + 1,
            )
            aggregates[key] = aggregate
        aggregate.update(row)

    notes = [
        (
            f"{path.name} is parsed as GridPACK ca-scalability-v2 csv_flat output. "
            f"Only the first {CSV_FLAT_PREVIEW_LIMIT} raw rows are kept in memory; "
            "branch-level summaries are streamed from the full file."
        )
    ]
    if fallback_note:
        notes.append(fallback_note)
    if rejected:
        notes.append(f"Rejected {rejected} csv_flat rows with missing branch keys or loading_percent.")

    return _flat_tables_from_aggregates(path, preview_rows, aggregates.values(), notes)


def _parse_flat_results_accelerated(
    path: Path,
    lookup: dict[str, str],
    backend_decision_path: Path,
    progress: ProgressCallback | None = None,
    total_estimate: int | None = None,
) -> tuple[dict[str, ParsedTable] | None, str]:
    try:
        backend = _lazy_backend(backend_decision_path)
    except Exception as exc:
        if _gpu_backend_required():
            raise RuntimeError(f"GPU csv_flat aggregation was required but {_requested_backend()} could not be used: {exc}") from exc
        return None, f"Accelerated csv_flat aggregation was skipped: {exc}"

    total_text = _format_rows(total_estimate)

    def _heartbeat_message(elapsed: float) -> str:
        return (
            f"Aggregating ~{total_text} contingency rows on the {_backend_label(backend.name)}... "
            f"(elapsed {_format_elapsed(elapsed)})"
        )

    try:
        if backend.name == "cudf":
            with _progress_heartbeat(progress, _heartbeat_message):
                data = _normalized_eager_flat_frame(path, lookup, backend)
                preview_rows = _preview_rows(path, lookup)
                keys = ["from_bus", "to_bus", "line_id", "section"]
                grouped = _flat_grouped_frame(data, keys)
                label_frame = _lazy_extreme_label_frame(data, keys)
                labels = _extreme_labels_from_frame(label_frame)
                aggregates = _aggregates_from_frame(grouped, labels)
            runtime_note = ""
        else:
            with _dask_runtime(backend) as runtime, _progress_heartbeat(progress, _heartbeat_message):
                data = _normalized_lazy_flat_frame(path, lookup, backend, backend_decision_path)
                preview_rows = _preview_rows(path, lookup)
                keys = ["from_bus", "to_bus", "line_id", "section"]
                grouped = _flat_grouped_frame(data, keys)
                label_frame = _lazy_extreme_label_frame(data, keys)
                grouped, label_frame = _compute_lazy_frames(grouped, label_frame, runtime=runtime)
                labels = _extreme_labels_from_frame(label_frame)
                aggregates = _aggregates_from_frame(grouped, labels)
                runtime_note = runtime.note
    except Exception as exc:
        if _gpu_backend_required():
            raise RuntimeError(f"GPU csv_flat aggregation with {_requested_backend()} failed: {exc}") from exc
        return None, (
            f"Accelerated csv_flat aggregation with {_requested_backend()} failed and Python streaming was used: {exc}"
        )

    notes = [
        _backend_aggregation_note(path, backend),
        _backend_runtime_note(backend),
    ]
    if runtime_note:
        notes.append(runtime_note)
    return _flat_tables_from_aggregates(path, preview_rows, aggregates, notes), ""


def _flat_tables_from_aggregates(
    path: Path,
    preview_rows: list[dict[str, object]],
    aggregates: Iterable[_BranchAggregate],
    notes: list[str],
) -> dict[str, ParsedTable]:
    aggregate_list = list(aggregates)
    preview = ParsedTable(CSV_FLAT_RESULTS_TABLE, path.name, list(_FLAT_RESULT_COLUMNS), preview_rows, list(notes))
    pflow_rows = [_aggregate_to_pflow_row(aggregate) for aggregate in aggregate_list]
    pflow_mm_rows = [_aggregate_to_pflow_mm_row(aggregate) for aggregate in aggregate_list]
    branch_rows = [_aggregate_to_branch_metadata_row(aggregate, path.name) for aggregate in aggregate_list]

    return {
        CSV_FLAT_RESULTS_TABLE: preview,
        "pflow": ParsedTable("pflow", path.name, list(_PFLOW_COLUMNS), pflow_rows, list(notes)),
        "pflow_mm": ParsedTable("pflow_mm", path.name, list(_PFLOW_MM_COLUMNS), pflow_mm_rows, list(notes)),
        CSV_FLAT_BRANCH_TABLE: ParsedTable(
            CSV_FLAT_BRANCH_TABLE,
            path.name,
            list(_BRANCH_COLUMNS),
            branch_rows,
            ["Branch keys were derived from csv_flat from_bus/to_bus/circuit_id/section columns."],
        ),
    }


def _preview_rows(
    path: Path,
    lookup: dict[str, str],
) -> list[dict[str, object]]:
    preview_rows: list[dict[str, object]] = []

    for raw_row in _dict_rows(path):
        row = _normalize_flat_result_row(raw_row, lookup)
        if row is None:
            continue
        if len(preview_rows) < CSV_FLAT_PREVIEW_LIMIT:
            preview_rows.append(row)
        else:
            break
    return preview_rows


def _normalized_lazy_flat_frame(
    path: Path,
    lookup: dict[str, str],
    backend: _LazyBackend,
    backend_decision_path: Path | None = None,
):
    columns = _flat_lazy_columns(lookup)
    data = _read_lazy_csv(backend, path, usecols=list(columns), blocksize=_dask_blocksize(backend_decision_path or path))
    data = data.rename(columns=columns)
    return _normalize_flat_frame_columns(data)


def _normalized_eager_flat_frame(path: Path, lookup: dict[str, str], backend: _LazyBackend):
    columns = _flat_lazy_columns(lookup)
    data = _read_eager_csv(backend, path, usecols=list(columns))
    data = data.rename(columns=columns)
    return _normalize_flat_frame_columns(data)


def _normalize_flat_frame_columns(data):
    for optional_column, default_value in (
        ("section", ""),
        ("event_idx", None),
        ("contingency", ""),
        ("rate_mva", None),
        ("viol", 0),
    ):
        if optional_column not in data.columns:
            data[optional_column] = default_value

    data = data.dropna(subset=["from_bus", "to_bus", "line_id", "loading_percent"])
    data["from_bus"] = data["from_bus"].astype("int64")
    data["to_bus"] = data["to_bus"].astype("int64")
    data["line_id"] = (
        data["line_id"]
        .astype("str")
        .str.strip()
        .str.strip("'")
        .str.strip('"')
        .str.replace(r"\.0$", "", regex=True)
    )
    data["section"] = (
        data["section"]
        .fillna("")
        .astype("str")
        .str.strip()
        .str.strip("'")
        .str.strip('"')
        .str.replace(r"\.0$", "", regex=True)
    )
    data["loading_percent"] = data["loading_percent"].astype("float64")
    data["rate_mva"] = data["rate_mva"].astype("float64")
    data["event_idx"] = data["event_idx"].fillna(-1).astype("float64")
    data["viol"] = data["viol"].fillna(0).astype("float64")
    data["overloaded"] = ((data["viol"] != 0) | (data["loading_percent"] >= 100.0)).astype("int64")
    data["base_loading"] = data["loading_percent"].where(data["event_idx"] == 0)
    data["abs_loading"] = data["loading_percent"].abs()
    return data


def _flat_grouped_frame(data, keys: list[str]):
    return data.groupby(keys).agg(
        {
            "loading_percent": ["count", "sum", "min", "max"],
            "abs_loading": "max",
            "base_loading": "max",
            "overloaded": "sum",
            "rate_mva": "first",
        }
    )


def _lazy_extreme_label_frame(data, keys: list[str]):
    max_values = data.groupby(keys)["abs_loading"].max().reset_index().rename(
        columns={"abs_loading": "max_abs_loading"}
    )
    candidates = data.merge(max_values, on=keys, how="inner")
    candidates = candidates[candidates["abs_loading"] == candidates["max_abs_loading"]]
    return candidates.groupby(keys).agg({"event_idx": "first", "contingency": "first"})


def _compute_lazy_frames(*frames, runtime: _DaskRuntime):
    try:
        import dask

        return dask.compute(*frames, **runtime.compute_kwargs)
    except Exception:
        return tuple(frame.compute(**runtime.compute_kwargs) for frame in frames)


@contextmanager
def _dask_runtime(backend: _LazyBackend):
    mode = _dask_cluster_mode()
    if mode == "off":
        yield _local_dask_runtime()
        return

    client = None
    cluster = None
    try:
        client, cluster, note = _create_dask_client(backend)
    except Exception as exc:
        if mode == "required":
            raise RuntimeError(f"Dask distributed runtime was required but could not be started: {exc}") from exc
        yield _local_dask_runtime(f"Dask distributed runtime was unavailable and local scheduler was used: {exc}")
        return

    try:
        yield _DaskRuntime({}, note)
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()
        if cluster is not None:
            with suppress(Exception):
                cluster.close()


def _create_dask_client(backend: _LazyBackend):
    memory_target = _memory_target()
    local_directory = _dask_temp_dir()
    if backend.name == "dask_cudf":
        from dask_cuda import LocalCUDACluster  # type: ignore[import-not-found]
        from distributed import Client  # type: ignore[import-not-found]

        cluster = LocalCUDACluster(**_cuda_cluster_kwargs(memory_target, local_directory))
        client = Client(cluster)
        return (
            client,
            cluster,
            "Dask-CUDA distributed runtime was used with "
            f"a {memory_target} worker memory target and {_device_memory_limit()} device memory limit.",
        )

    from distributed import Client, LocalCluster  # type: ignore[import-not-found]

    cluster = LocalCluster(
        n_workers=1,
        threads_per_worker=max(os.cpu_count() or 1, 1),
        processes=False,
        memory_limit=memory_target,
        local_directory=local_directory,
    )
    client = Client(cluster)
    return client, cluster, f"Dask distributed runtime was used with a {memory_target} worker memory limit."


def _cuda_cluster_kwargs(memory_target: str, local_directory: str) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "n_workers": 1,
        "threads_per_worker": 1,
        "memory_limit": memory_target,
        "local_directory": local_directory,
    }
    device_limit = _device_memory_limit()
    if device_limit:
        kwargs["device_memory_limit"] = device_limit
    return kwargs


def _local_dask_runtime(reason: str = "") -> _DaskRuntime:
    note = f"Local Dask scheduler '{_dask_scheduler()}' was used."
    if reason:
        note = f"{note} {reason}"
    return _DaskRuntime({"scheduler": _dask_scheduler()}, note)


@contextmanager
def _dask_scheduler_config(runtime: _DaskRuntime):
    scheduler = runtime.compute_kwargs.get("scheduler")
    if not scheduler:
        yield
        return
    try:
        import dask
    except Exception:
        yield
        return
    with dask.config.set(scheduler=scheduler):
        yield


def _extreme_labels_from_frame(frame) -> dict[tuple[object, object, str, str], _ExtremeLabels]:
    records = _records_from_frame(frame.reset_index())

    labels = {}
    for row in records:
        key = (
            _int_value(row.get("from_bus")),
            _int_value(row.get("to_bus")),
            _clean_text(row.get("line_id")),
            _clean_text(row.get("section")),
        )
        labels[key] = _ExtremeLabels(
            max_abs_event_idx=_event_value(row.get("event_idx")),
            max_abs_contingency=_clean_text(row.get("contingency")),
        )
    return labels


def _backend_runtime_note(backend: _LazyBackend) -> str:
    if backend.name == "dask_cudf":
        return "RAPIDS dask-cudf GPU backend was used for csv_flat aggregation."
    if backend.name == "cudf":
        return "RAPIDS cuDF GPU backend was used for csv_flat aggregation."
    if backend.name == "dask":
        return (
            "CPU Dask backend was used for csv_flat aggregation. Install RAPIDS cuDF/dask-cudf/dask-cuda "
            "and set GRIDLENS_CSV_FLAT_BACKEND=dask_cudf or cudf to require GPU execution."
        )
    return f"{backend.name} backend was used for csv_flat aggregation."


def _backend_aggregation_note(path: Path, backend: _LazyBackend) -> str:
    if backend.name == "cudf":
        return f"{path.name} was aggregated with cuDF on one GPU."
    return (
        f"{path.name} was aggregated with {backend.name}; partitions are bounded by "
        f"{_dask_blocksize(path)} and the memory target is {_memory_target()}."
    )


def _flat_lazy_columns(lookup: dict[str, str]) -> dict[str, str]:
    aliases = {
        "event_idx": _EVENT_ALIASES,
        "contingency": _CONTINGENCY_ALIASES,
        "from_bus": _FROM_BUS_ALIASES,
        "to_bus": _TO_BUS_ALIASES,
        "line_id": _CIRCUIT_ALIASES,
        "section": _SECTION_ALIASES,
        "rate_mva": ("rate_mva", "rate", "ratec"),
        "loading_percent": _LOADING_ALIASES,
        "viol": ("viol", "violation"),
    }
    columns: dict[str, str] = {}
    for canonical, column_aliases in aliases.items():
        column = _column(lookup, column_aliases)
        if column:
            columns[column] = canonical
    return columns


def _aggregates_from_frame(
    frame,
    labels: dict[tuple[object, object, str, str], _ExtremeLabels],
) -> list[_BranchAggregate]:
    frame = _flatten_aggregate_frame(frame)
    rows = _records_from_frame(frame)
    aggregates = []
    for index, row in enumerate(rows, start=1):
        key = (
            _int_value(row.get("from_bus")),
            _int_value(row.get("to_bus")),
            _clean_text(row.get("line_id")),
            _clean_text(row.get("section")),
        )
        label = labels.get(key, _ExtremeLabels())
        count = int(_float_value(row.get("contingency_count")) or 0)
        sum_loading = _float_value(row.get("sum_loading")) or 0.0
        aggregate = _BranchAggregate(
            from_bus=key[0],
            to_bus=key[1],
            line_id=key[2],
            section=key[3],
            row_index=index,
            count=count,
            overload_count=int(_float_value(row.get("overload_count")) or 0),
            sum_loading=sum_loading,
            min_loading=_float_value(row.get("min_loading")),
            max_loading=_float_value(row.get("max_loading")),
            max_abs_loading=_float_value(row.get("max_abs_loading")),
            base_loading=_float_value(row.get("base_loading")),
            min_event_idx=label.min_event_idx,
            max_event_idx=label.max_event_idx,
            max_abs_event_idx=label.max_abs_event_idx,
            max_abs_contingency=label.max_abs_contingency,
            rate_mva=_float_value(row.get("rate_mva")),
        )
        aggregates.append(aggregate)
    return aggregates


def _flatten_aggregate_frame(frame):
    try:
        import pandas as pd

        is_multi_index = isinstance(frame.columns, pd.MultiIndex)
    except Exception:
        is_multi_index = False

    columns = list(frame.columns)
    if is_multi_index or any(isinstance(column, tuple) for column in columns):
        frame.columns = [
            "_".join(str(part) for part in (column if isinstance(column, tuple) else (column,)) if str(part))
            for column in columns
        ]
    rename = {
        "loading_percent_count": "contingency_count",
        "loading_percent_sum": "sum_loading",
        "loading_percent_min": "min_loading",
        "loading_percent_max": "max_loading",
        "abs_loading_max": "max_abs_loading",
        "base_loading_max": "base_loading",
        "overloaded_sum": "overload_count",
        "rate_mva_first": "rate_mva",
    }
    return frame.reset_index().rename(columns=rename)


def _records_from_frame(frame) -> list[dict[str, object]]:
    if hasattr(frame, "to_pandas"):
        frame = frame.to_pandas()
    return frame.to_dict(orient="records")


def _parse_convergence(path: Path) -> tuple[ParsedTable, ParsedTable]:
    lookup = _column_lookup(_header(path))
    convergence_rows: list[dict[str, object]] = []
    success_rows: list[dict[str, object]] = []
    rejected = 0

    for raw_row in _dict_rows(path):
        event_idx = _int_value(raw_row.get(_column(lookup, _EVENT_ALIASES)))
        contingency = _clean_text(raw_row.get(_column(lookup, _CONTINGENCY_ALIASES)))
        if event_idx is None or not contingency:
            rejected += 1
            continue

        status_code = _clean_text(raw_row.get(_column(lookup, ("status_code", "status")))).upper()
        converged = _bool_value(raw_row.get(_column(lookup, ("converged", "success"))))
        success = bool(converged) and (not status_code or status_code == "OK")
        violation = "none" if success else (status_code.lower() or "failed")
        raw_line = f"{event_idx},{contingency},{status_code or 'unknown'}"

        convergence_rows.append(
            {
                "event_idx": event_idx,
                "contingency": contingency,
                "type": _clean_text(raw_row.get(_column(lookup, ("type",)))),
                "converged": converged,
                "iterations": _int_value(raw_row.get(_column(lookup, ("iterations",)))),
                "final_tolerance": _float_value(raw_row.get(_column(lookup, ("final_tolerance",)))),
                "max_p_bus": _int_value(raw_row.get(_column(lookup, ("max_p_bus",)))),
                "max_p_mismatch": _float_value(raw_row.get(_column(lookup, ("max_p_mismatch",)))),
                "max_q_bus": _int_value(raw_row.get(_column(lookup, ("max_q_bus",)))),
                "max_q_mismatch": _float_value(raw_row.get(_column(lookup, ("max_q_mismatch",)))),
                "status_code": status_code,
            }
        )
        success_rows.append(
            {
                "contingency_index": event_idx,
                "success": success,
                "violation": violation,
                "isolated_warning": status_code == "ISLANDED",
                "raw_line": raw_line,
            }
        )

    notes = [f"{path.name} was parsed as ca-scalability-v2 contingency convergence/status output."]
    if rejected:
        notes.append(f"Rejected {rejected} convergence rows with missing event_idx or contingency.")
    return (
        ParsedTable(CSV_FLAT_CONVERGENCE_TABLE, path.name, list(_CONVERGENCE_COLUMNS), convergence_rows, list(notes)),
        ParsedTable("success", path.name, list(_SUCCESS_COLUMNS), success_rows, list(notes)),
    )


def _parse_bus_metadata(path: Path) -> tuple[ParsedTable, ParsedTable]:
    lookup = _column_lookup(_header(path))
    bus_rows: list[dict[str, object]] = []
    areas: dict[int, str] = {}
    rejected = 0

    for raw_row in _dict_rows(path):
        bus_id = _int_value(raw_row.get(_column(lookup, ("bus_id", "bus"))))
        if bus_id is None:
            rejected += 1
            continue
        area = _int_value(raw_row.get(_column(lookup, ("area", "area_id"))))
        area_name = _clean_text(raw_row.get(_column(lookup, ("area_name", "control_area"))))
        if area is not None and area_name:
            areas.setdefault(area, area_name)
        bus_rows.append(
            {
                "bus_id": bus_id,
                "bus_name": _clean_text(raw_row.get(_column(lookup, ("bus_name", "name")))),
                "base_kv": _float_value(raw_row.get(_column(lookup, ("base_kv", "kv")))),
                "area": area,
                "zone": _int_value(raw_row.get(_column(lookup, ("zone", "zone_id")))),
                "owner": _int_value(raw_row.get(_column(lookup, ("owner", "owner_id")))),
                "vm": _float_value(raw_row.get(_column(lookup, ("vm", "voltage_pu")))),
                "va": _float_value(raw_row.get(_column(lookup, ("va", "angle_deg")))),
                "area_name": area_name,
                "zone_name": _clean_text(raw_row.get(_column(lookup, ("zone_name",)))),
                "owner_name": _clean_text(raw_row.get(_column(lookup, ("owner_name",)))),
            }
        )

    area_rows = [
        {"area": area, "slack_bus": None, "pdes": None, "ptol": None, "area_name": name}
        for area, name in sorted(areas.items())
    ]
    notes = [f"{path.name} was parsed as ca-scalability-v2 bus and control-area metadata."]
    if rejected:
        notes.append(f"Rejected {rejected} bus metadata rows without a bus_id.")
    return (
        ParsedTable("bus_metadata", path.name, list(_BUS_COLUMNS), bus_rows, list(notes)),
        ParsedTable("area_metadata", path.name, list(AREA_METADATA_COLUMNS), area_rows, list(notes)),
    )


def _normalize_flat_result_row(raw_row: dict[str, str], lookup: dict[str, str]) -> dict[str, object] | None:
    from_bus = _int_value(raw_row.get(_column(lookup, _FROM_BUS_ALIASES)))
    to_bus = _int_value(raw_row.get(_column(lookup, _TO_BUS_ALIASES)))
    line_id = _clean_text(raw_row.get(_column(lookup, _CIRCUIT_ALIASES)))
    loading = _float_value(raw_row.get(_column(lookup, _LOADING_ALIASES)))
    if from_bus is None or to_bus is None or not line_id or loading is None:
        return None

    return {
        "event_idx": _event_value(raw_row.get(_column(lookup, _EVENT_ALIASES))),
        "contingency": _clean_text(raw_row.get(_column(lookup, _CONTINGENCY_ALIASES))),
        "from_bus": from_bus,
        "to_bus": to_bus,
        "line_id": line_id,
        "section": _clean_text(raw_row.get(_column(lookup, _SECTION_ALIASES))),
        "p_from_mw": _float_value(raw_row.get(_column(lookup, ("p_from_mw", "pflow", "p_mw")))),
        "q_from_mvar": _float_value(raw_row.get(_column(lookup, ("q_from_mvar", "qflow", "q_mvar")))),
        "mva_from": _float_value(raw_row.get(_column(lookup, ("mva_from", "mva")))),
        "rate_mva": _float_value(raw_row.get(_column(lookup, ("rate_mva", "rate", "ratec")))),
        "loading_percent": loading,
        "viol": _int_value(raw_row.get(_column(lookup, ("viol", "violation")))) or 0,
        "v_from_pu": _float_value(raw_row.get(_column(lookup, ("v_from_pu",)))),
        "v_to_pu": _float_value(raw_row.get(_column(lookup, ("v_to_pu",)))),
        "ang_from_deg": _float_value(raw_row.get(_column(lookup, ("ang_from_deg",)))),
        "ang_to_deg": _float_value(raw_row.get(_column(lookup, ("ang_to_deg",)))),
    }


def _lazy_backend(csv_path: Path | None = None) -> _LazyBackend:
    requested = _requested_backend()
    errors: list[str] = []
    backend_order = _auto_backend_order(csv_path) if requested == "auto" else (requested,)

    for backend_name in backend_order:
        if backend_name == "python":
            break
        if backend_name == "dask":
            if not _cpu_dask_allowed():
                errors.append("dask: CPU Dask fallback requires user acknowledgement")
                continue
            if not _gpu_backends_unavailable():
                errors.append("dask: CPU Dask fallback is used only when cuDF and dask-cuDF are unavailable")
                continue
        try:
            if backend_name == "dask_cudf":
                import dask_cudf  # type: ignore[import-not-found]

                return _LazyBackend("dask_cudf", dask_cudf)
            if backend_name == "cudf":
                import cudf  # type: ignore[import-not-found]

                return _LazyBackend("cudf", cudf)
            if backend_name == "dask":
                import dask.dataframe as dd  # type: ignore[import-not-found]

                return _LazyBackend("dask", dd)
        except Exception as exc:
            errors.append(f"{backend_name}: {exc}")

    detail = "; ".join(errors) if errors else "backend set to python"
    raise RuntimeError(detail)


def _auto_backend_order(csv_path: Path | None = None) -> tuple[str, ...]:
    if _should_partition_with_dask_cudf(csv_path):
        return ("dask_cudf", "dask")
    return ("cudf", "dask_cudf", "dask")


def _largest_existing_path(paths: Iterable[Path]) -> Path | None:
    largest_path = None
    largest_size = -1
    for path in paths:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > largest_size:
            largest_path = path
            largest_size = size
    return largest_path


def _should_partition_with_dask_cudf(csv_path: Path | None) -> bool:
    available = _available_memory_limit()
    if csv_path is None or available is None:
        return False
    try:
        size = csv_path.stat().st_size
    except OSError:
        return False
    return size > int(available * CSV_FLAT_CUDF_MEMORY_FRACTION)


def _cpu_dask_allowed() -> bool:
    value = os.environ.get(CSV_FLAT_ALLOW_CPU_DASK_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _gpu_backends_unavailable() -> bool:
    return not _backend_importable("cudf") and not _backend_importable("dask_cudf")


def _backend_importable(backend_name: str) -> bool:
    try:
        if backend_name == "cudf":
            import cudf  # type: ignore[import-not-found]  # noqa: F401
        elif backend_name == "dask_cudf":
            import dask_cudf  # type: ignore[import-not-found]  # noqa: F401
        elif backend_name == "dask":
            import dask.dataframe  # type: ignore[import-not-found]  # noqa: F401
        else:
            return False
    except Exception:
        return False
    return True


def _read_lazy_csv(
    backend: _LazyBackend,
    path: Path,
    *,
    usecols: list[str] | None = None,
    blocksize: str,
):
    kwargs = {
        "blocksize": blocksize,
    }
    if usecols is not None:
        kwargs["usecols"] = usecols
    if backend.name == "dask":
        kwargs["assume_missing"] = True

    try:
        return backend.module.read_csv(str(path), **kwargs)
    except TypeError:
        kwargs.pop("blocksize", None)
        kwargs["chunksize"] = blocksize
        return backend.module.read_csv(str(path), **kwargs)


def _read_eager_csv(
    backend: _LazyBackend,
    path: Path,
    *,
    usecols: list[str] | None = None,
):
    kwargs = {}
    if usecols is not None:
        kwargs["usecols"] = usecols
    return backend.module.read_csv(str(path), **kwargs)


def _requested_backend() -> str:
    value = os.environ.get("GRIDLENS_CSV_FLAT_BACKEND", CSV_FLAT_DEFAULT_BACKEND)
    value = value.strip().lower().replace("-", "_")
    if value in {"auto", "dask_cudf", "cudf", "dask", "python"}:
        return value
    return CSV_FLAT_DEFAULT_BACKEND


def _gpu_backend_required() -> bool:
    return _requested_backend() in {"dask_cudf", "cudf"}


def _dask_blocksize(csv_path: Path | None = None) -> str:
    explicit = os.environ.get("GRIDLENS_CSV_FLAT_BLOCKSIZE", "").strip()
    if explicit:
        return explicit
    if csv_path is None or not _should_partition_with_dask_cudf(csv_path):
        return CSV_FLAT_DEFAULT_BLOCKSIZE
    budget = _memory_target_bytes()
    if budget is None:
        return CSV_FLAT_DEFAULT_BLOCKSIZE
    default_bytes = _parse_memory_bytes(CSV_FLAT_DEFAULT_BLOCKSIZE) or 256 * 1024**2
    blocksize = max(CSV_FLAT_MIN_BLOCKSIZE_BYTES, min(default_bytes, budget // 16))
    return _format_memory_target(blocksize)


def _dask_scheduler() -> str:
    return os.environ.get("GRIDLENS_CSV_FLAT_SCHEDULER", CSV_FLAT_DEFAULT_SCHEDULER).strip() or CSV_FLAT_DEFAULT_SCHEDULER


def _memory_target() -> str:
    requested = os.environ.get("GRIDLENS_CSV_FLAT_MEMORY_TARGET", CSV_FLAT_MEMORY_TARGET).strip() or CSV_FLAT_MEMORY_TARGET
    requested_bytes = _parse_memory_bytes(requested)
    available_limit = _available_memory_limit()
    if requested_bytes is None or available_limit is None or requested_bytes <= int(available_limit * CSV_FLAT_MEMORY_HEADROOM):
        return requested
    return _format_memory_target(int(available_limit * CSV_FLAT_MEMORY_HEADROOM))


def _memory_target_bytes() -> int | None:
    return _parse_memory_bytes(_memory_target())


def _available_memory_limit() -> int | None:
    proc_available = _proc_mem_available()
    distributed_limit = _distributed_memory_limit()
    candidates = [value for value in (proc_available, distributed_limit) if value is not None and value > 0]
    return min(candidates) if candidates else None


def _proc_mem_available() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def _distributed_memory_limit() -> int | None:
    try:
        from distributed.system import MEMORY_LIMIT  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        value = int(MEMORY_LIMIT)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


def _parse_memory_bytes(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]i?b?|bytes?)?\s*", value, flags=re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    units = {
        "b": 1,
        "byte": 1,
        "bytes": 1,
        "k": 1000,
        "kb": 1000,
        "kib": 1024,
        "m": 1000**2,
        "mb": 1000**2,
        "mib": 1024**2,
        "g": 1000**3,
        "gb": 1000**3,
        "gib": 1024**3,
        "t": 1000**4,
        "tb": 1000**4,
        "tib": 1024**4,
    }
    multiplier = units.get(unit)
    if multiplier is None:
        return None
    return int(number * multiplier)


def _format_memory_target(value: int) -> str:
    if value >= 1024**3:
        return f"{max(value // 1024**3, 1)}GiB"
    return f"{max(value // 1024**2, 1)}MiB"


def _format_file_size(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GiB"
    if value >= 1024**2:
        return f"{value / 1024**2:.2f} MiB"
    if value >= 1024:
        return f"{value / 1024:.2f} KiB"
    return f"{value} bytes"


def _dask_cluster_mode() -> str:
    value = os.environ.get("GRIDLENS_CSV_FLAT_CLUSTER", CSV_FLAT_DEFAULT_CLUSTER)
    value = value.strip().lower()
    if value in {"auto", "off", "required"}:
        return value
    return CSV_FLAT_DEFAULT_CLUSTER


def _dask_temp_dir() -> str:
    return os.environ.get("GRIDLENS_DASK_TEMP_DIR", CSV_FLAT_DEFAULT_DASK_TEMP_DIR).strip() or CSV_FLAT_DEFAULT_DASK_TEMP_DIR


def _device_memory_limit() -> str:
    value = os.environ.get("GRIDLENS_CSV_FLAT_DEVICE_MEMORY_LIMIT", CSV_FLAT_DEFAULT_DEVICE_MEMORY_LIMIT)
    return value.strip() or CSV_FLAT_DEFAULT_DEVICE_MEMORY_LIMIT


def _aggregate_to_pflow_row(aggregate: _BranchAggregate) -> dict[str, object]:
    mean_loading = aggregate.mean_loading
    return {
        "row_index": aggregate.row_index,
        "from_bus": aggregate.from_bus,
        "to_bus": aggregate.to_bus,
        "line_id": aggregate.line_id,
        "section": aggregate.section,
        "average": _round(mean_loading),
        "rms_average": None,
        "rms_base": None,
        "average_utilization_pct": _round(mean_loading),
        "contingency_count": aggregate.count,
        "utilization_source": "csv_flat.loading_percent",
    }


def _aggregate_to_pflow_mm_row(aggregate: _BranchAggregate) -> dict[str, object]:
    base = aggregate.base_loading
    min_value = aggregate.min_loading
    max_value = aggregate.max_loading
    return {
        "row_index": aggregate.row_index,
        "from_bus": aggregate.from_bus,
        "to_bus": aggregate.to_bus,
        "line_id": aggregate.line_id,
        "section": aggregate.section,
        "base_value": _round(base),
        "min_value": _round(min_value),
        "max_value": _round(max_value),
        "min_deviation": _round(min_value - (base or 0.0)) if min_value is not None and base is not None else None,
        "max_deviation": _round(max_value - (base or 0.0)) if max_value is not None and base is not None else None,
        "min_allowable": 0.0,
        "max_allowable": 100.0,
        "min_contingency": aggregate.min_event_idx,
        "max_contingency": aggregate.max_abs_event_idx,
        "base_utilization_pct": _round(base),
        "mean_utilization_pct": _round(aggregate.mean_loading),
        "max_utilization_pct": _round(aggregate.max_abs_loading),
        "max_utilization_contingency": aggregate.max_abs_event_idx,
        "max_contingency_label": aggregate.max_abs_contingency,
        "contingency_count": aggregate.count,
        "overload_count": aggregate.overload_count,
        "utilization_source": "csv_flat.loading_percent",
    }


def _aggregate_to_branch_metadata_row(aggregate: _BranchAggregate, source_file: str) -> dict[str, object]:
    rate = _round(aggregate.rate_mva)
    return {
        "from_bus": aggregate.from_bus,
        "to_bus": aggregate.to_bus,
        "line_id": aggregate.line_id,
        "section": aggregate.section,
        "ratea": rate,
        "rateb": rate,
        "ratec": rate,
        "rate_mva": rate,
        "status": 1,
        "raw_branch_type": NONTRANSFORMER_BRANCH,
        "source_file": source_file,
    }


def _find_matching_csv(
    paths: Iterable[Path],
    predicate,
    preferred_terms: tuple[str, ...] = (),
) -> Path | None:
    matches = [path for path in paths if predicate(_header(path))]
    for term in preferred_terms:
        for path in matches:
            if term in path.name.lower():
                return path
    return matches[0] if matches else None


def _is_flat_results_header(header: list[str]) -> bool:
    lookup = _column_lookup(header)
    required = [
        _column(lookup, _FROM_BUS_ALIASES),
        _column(lookup, _TO_BUS_ALIASES),
        _column(lookup, _CIRCUIT_ALIASES),
        _column(lookup, _LOADING_ALIASES),
    ]
    return all(required)


def _is_convergence_header(header: list[str]) -> bool:
    lookup = _column_lookup(header)
    return all(_column(lookup, aliases) for aliases in (_EVENT_ALIASES, _CONTINGENCY_ALIASES, ("converged",), ("status_code", "status")))


def _is_bus_metadata_header(header: list[str]) -> bool:
    lookup = _column_lookup(header)
    return all(_column(lookup, aliases) for aliases in (("bus_id", "bus"), ("base_kv", "kv"), ("area", "area_id")))


def _dict_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


# --- Progress reporting for the (often very large) csv_flat aggregation --------
#
# The flat results file can be many gigabytes / tens of millions of rows, so the
# "Parsing GridPACK contingency outputs" phase is the longest single step of
# analysis. We report fine-grained progress two ways, depending on which backend
# runs:
#   * Python streaming path (a loop we own): real "row n of ~N" updates.
#   * Accelerated GPU/Dask path (one opaque bulk compute): a heartbeat with the
#     data scale and elapsed time, since a distributed groupby does not expose a
#     row cursor. The progress bar animates in busy mode meanwhile.

_PROGRESS_ROW_INTERVAL = 250_000
_HEARTBEAT_SECONDS = 1.0


def _estimate_total_rows(path: Path, sample_bytes: int = 2_000_000) -> int | None:
    """Estimate the data-row count of a CSV cheaply, without a full read.

    Reads a small head sample, derives the average bytes-per-line, and scales by
    the file size. Returns ``None`` if it cannot be estimated. The result is an
    estimate (hence the "~" the UI shows), not an exact count -- an exact count
    would require a second full pass over a multi-gigabyte file.
    """
    try:
        file_size = path.stat().st_size
        with path.open("rb") as handle:
            sample = handle.read(sample_bytes)
    except OSError:
        return None
    if not sample:
        return None
    newlines = sample.count(b"\n")
    if newlines <= 1:
        return None
    # Bytes consumed up to the last complete line in the sample.
    consumed = sample.rfind(b"\n") + 1
    if consumed <= 0:
        return None
    avg_line_bytes = consumed / newlines
    if avg_line_bytes <= 0:
        return None
    estimated_lines = file_size / avg_line_bytes
    # Subtract the header row; never report a negative or absurdly small value.
    return max(int(estimated_lines) - 1, 0) or None


def _format_rows(count: int | None) -> str:
    if not count:
        return "many"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return f"{count:,}"


@contextmanager
def _progress_heartbeat(progress: ProgressCallback | None, message_factory: Callable[[float], str]):
    """Emit a periodic progress update while a blocking step runs.

    ``message_factory`` receives elapsed seconds and returns the status text.
    Used for the accelerated aggregation, whose single ``dask.compute`` call
    would otherwise leave the status frozen for minutes.
    """
    if progress is None:
        yield
        return

    start = time.monotonic()
    stop = threading.Event()

    def _beat() -> None:
        # Emit immediately, then every _HEARTBEAT_SECONDS until told to stop.
        while True:
            elapsed = time.monotonic() - start
            with suppress(Exception):
                report(progress, PHASE_PARSE, message_factory(elapsed), None)
            if stop.wait(_HEARTBEAT_SECONDS):
                return

    thread = threading.Thread(target=_beat, name="csv-flat-progress", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=_HEARTBEAT_SECONDS)


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}" if minutes else f"{secs}s"


def _backend_label(backend_name: str) -> str:
    return {
        "cudf": "GPU (cuDF)",
        "dask_cudf": "GPU (dask-cuDF)",
        "dask": "CPU (Dask)",
    }.get(backend_name, backend_name or "accelerated backend")


def _header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            return next(reader, [])
    except OSError:
        return []


def _column_lookup(header: list[str]) -> dict[str, str]:
    return {_column_key(column): column for column in header if column}


def _column(lookup: dict[str, str], aliases: Iterable[str]) -> str:
    for alias in aliases:
        column = lookup.get(_column_key(alias))
        if column:
            return column
    return ""


def _column_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _event_value(value: object) -> object:
    parsed = _int_value(value)
    return parsed if parsed is not None else _clean_text(value)


def _int_value(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _float_value(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bool_value(value: object) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "ok", "converged"}:
        return True
    if text in {"false", "0", "no", "n", "failed", "diverged"}:
        return False
    return None


def _is_truthy(value: object) -> bool:
    parsed = _bool_value(value)
    if parsed is not None:
        return parsed
    number = _float_value(value)
    return bool(number)


def _is_base_case(event_idx: object, contingency: object) -> bool:
    if _int_value(event_idx) == 0:
        return True
    return _column_key(str(contingency or "")) in {"base", "base_case", "basecase"}


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().strip("'").strip('"').split())


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None and math.isfinite(value) else None


def _metadata_key(row: dict[str, object]) -> tuple[object, object, str]:
    return (_int_value(row.get("from_bus")), _int_value(row.get("to_bus")), _clean_text(row.get("line_id")))


def _flat_row_key(row: dict[str, object]) -> tuple[object, object, str, str]:
    return (
        _int_value(row.get("from_bus")),
        _int_value(row.get("to_bus")),
        _clean_text(row.get("line_id")),
        _clean_text(row.get("section")),
    )


def _find_work_file(run_path: Path, file_name: str) -> Path | None:
    work_dir = run_path / "work"
    direct = work_dir / file_name
    if direct.exists():
        return direct
    matches = sorted(path for path in work_dir.rglob(file_name) if path.is_file())
    return matches[0] if matches else None


def _dedupe(values: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "CSV_FLAT_BRANCH_TABLE",
    "CSV_FLAT_ALLOW_CPU_DASK_ENV",
    "CSV_FLAT_BUS_TABLE",
    "CSV_FLAT_CONVERGENCE_TABLE",
    "CSV_FLAT_RESULTS_TABLE",
    "ConversionResult",
    "convert_csv_to_parquet",
    "cpu_dask_fallback_warning",
    "ensure_csv_flat_parquet",
    "merge_csv_flat_branch_metadata",
    "parse_csv_flat_outputs",
    "parse_csv_flat_success",
]
