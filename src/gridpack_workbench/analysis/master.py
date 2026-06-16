from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from gridpack_workbench.analysis.dataset import RunAnalysisDataset, build_run_analysis
from gridpack_workbench.analysis.gpu_pandas import get_pandas
from gridpack_workbench.analysis.parsers import ParsedTable, parse_all_output_tables


MASTER_DATASET_VERSION = "2026.06.16"
BRANCH_KEYS = ["from_bus", "to_bus", "line_id"]
BRANCH_OUTPUT_TABLES = ["pflow", "pflow_mm", "qflow", "qflow_mm", "perf_mm", "line_flt_cnt"]
UTILIZATION_COLUMNS = [
    "base_case_utilization_pct",
    "mean_contingency_utilization_pct",
    "max_contingency_utilization_pct",
]


@dataclass(slots=True)
class MasterExportResult:
    exports_dir: Path
    master_csv: Path
    master_cleaned_csv: Path
    outliers_csv: Path
    row_count: int
    cleaned_row_count: int
    outlier_row_count: int
    outlier_threshold_pct: float
    code_path: Path

    def as_dict(self) -> dict[str, object]:
        return {
            "exports_dir": str(self.exports_dir),
            "master_csv": str(self.master_csv),
            "master_cleaned_csv": str(self.master_cleaned_csv),
            "outliers_csv": str(self.outliers_csv),
            "row_count": self.row_count,
            "cleaned_row_count": self.cleaned_row_count,
            "outlier_row_count": self.outlier_row_count,
            "outlier_threshold_pct": self.outlier_threshold_pct,
            "code_path": str(self.code_path),
            "dataset_version": MASTER_DATASET_VERSION,
        }


def build_branch_master_exports(
    run_dir: str | Path,
    dataset: RunAnalysisDataset | None = None,
    outlier_threshold_pct: float = 1000.0,
) -> MasterExportResult:
    pd = get_pandas()
    run_path = Path(run_dir).expanduser().resolve()
    dataset = dataset or build_run_analysis(run_path)
    exports_dir = run_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    master = _branch_base_frame(pd, dataset.tables)
    for table_name in BRANCH_OUTPUT_TABLES:
        table = dataset.tables.get(table_name)
        frame = _table_frame(pd, table, table_name)
        if frame is not None and not frame.empty:
            master = master.merge(frame, how="outer", on=BRANCH_KEYS)

    master = _normalize_master_columns(pd, master)
    master = _add_utilization_columns(pd, master)
    master = _add_outlier_reasons(master, outlier_threshold_pct)

    outlier_mask = master["outlier_reason"].fillna("").astype(str) != ""
    outliers = master.loc[outlier_mask].copy()
    cleaned = master.loc[~outlier_mask].copy()

    master_csv = exports_dir / "master.csv"
    cleaned_csv = exports_dir / "master_cleaned.csv"
    outliers_csv = exports_dir / "outliers.csv"
    master.to_csv(master_csv, index=False)
    cleaned.to_csv(cleaned_csv, index=False)
    outliers.to_csv(outliers_csv, index=False)

    return MasterExportResult(
        exports_dir=exports_dir,
        master_csv=master_csv,
        master_cleaned_csv=cleaned_csv,
        outliers_csv=outliers_csv,
        row_count=int(len(master)),
        cleaned_row_count=int(len(cleaned)),
        outlier_row_count=int(len(outliers)),
        outlier_threshold_pct=outlier_threshold_pct,
        code_path=Path(__file__).resolve(),
    )


def ensure_branch_master_exports(
    run_dir: str | Path,
    dataset: RunAnalysisDataset | None = None,
    outlier_threshold_pct: float = 1000.0,
) -> MasterExportResult:
    run_path = Path(run_dir).expanduser().resolve()
    exports_dir = run_path / "exports"
    master_csv = exports_dir / "master.csv"
    cleaned_csv = exports_dir / "master_cleaned.csv"
    outliers_csv = exports_dir / "outliers.csv"
    if master_csv.exists() and cleaned_csv.exists() and outliers_csv.exists():
        pd = get_pandas()
        master = pd.read_csv(master_csv)
        cleaned = pd.read_csv(cleaned_csv)
        outliers = pd.read_csv(outliers_csv)
        return MasterExportResult(
            exports_dir=exports_dir,
            master_csv=master_csv,
            master_cleaned_csv=cleaned_csv,
            outliers_csv=outliers_csv,
            row_count=int(len(master)),
            cleaned_row_count=int(len(cleaned)),
            outlier_row_count=int(len(outliers)),
            outlier_threshold_pct=outlier_threshold_pct,
            code_path=Path(__file__).resolve(),
        )
    if dataset is None and (run_path / "reports" / "tables").exists():
        dataset = _dataset_from_existing_report_tables(run_path)
    return build_branch_master_exports(run_path, dataset=dataset, outlier_threshold_pct=outlier_threshold_pct)


def read_master_cleaned(run_dir: str | Path):
    pd = get_pandas()
    path = Path(run_dir).expanduser().resolve() / "exports" / "master_cleaned.csv"
    return pd.read_csv(path)


def _branch_base_frame(pd, tables: dict[str, ParsedTable]):
    raw_branches = _table_to_frame(pd, tables.get("branch_metadata"))
    if not raw_branches.empty:
        return _coerce_keys(raw_branches)

    frames = []
    for table_name in BRANCH_OUTPUT_TABLES:
        table = tables.get(table_name)
        frame = _table_to_frame(pd, table)
        if not frame.empty:
            frames.append(_coerce_keys(frame[BRANCH_KEYS].copy()).drop_duplicates())
    if frames:
        base = frames[0]
        for frame in frames[1:]:
            base = base.merge(frame, how="outer", on=BRANCH_KEYS)
        return base.drop_duplicates()
    return pd.DataFrame(columns=BRANCH_KEYS)


def _dataset_from_existing_report_tables(run_path: Path) -> RunAnalysisDataset:
    pd = get_pandas()
    report_dir = run_path / "reports"
    table_dir = report_dir / "tables"
    parsed = parse_all_output_tables(run_path)
    tables: dict[str, ParsedTable] = {}
    table_files: dict[str, dict[str, str]] = {}
    for name, parsed_table in parsed.items():
        csv_path = table_dir / f"{name}.csv"
        json_path = table_dir / f"{name}.json"
        if csv_path.exists():
            frame = pd.read_csv(csv_path)
            rows = frame.to_dict(orient="records")
            columns = list(frame.columns)
            tables[name] = ParsedTable(name, parsed_table.source_file, columns, rows, parsed_table.notes)
            table_files[name] = {"csv": str(csv_path), "json": str(json_path) if json_path.exists() else ""}
        else:
            tables[name] = parsed_table
    return RunAnalysisDataset(
        run_dir=run_path,
        report_dir=report_dir,
        table_dir=table_dir,
        manifest_path=report_dir / "analysis_manifest.json",
        tables=tables,
        metrics={},
        table_files=table_files,
        generated_at="",
    )


def _table_frame(pd, table: ParsedTable | None, table_name: str):
    frame = _table_to_frame(pd, table)
    if frame.empty:
        return None
    frame = _coerce_keys(frame)
    rename = {column: f"{table_name}_{column}" for column in frame.columns if column not in BRANCH_KEYS}
    return frame.rename(columns=rename)


def _table_to_frame(pd, table: ParsedTable | None):
    if not table or not table.rows:
        return pd.DataFrame(columns=table.columns if table else [])
    return pd.DataFrame(table.rows)


def _coerce_keys(frame):
    for column in ("from_bus", "to_bus"):
        if column in frame.columns:
            frame[column] = frame[column].astype("Int64")
    if "line_id" in frame.columns:
        frame["line_id"] = frame["line_id"].astype(str).str.strip().str.strip("'").str.strip('"')
    return frame


def _normalize_master_columns(pd, master):
    for key in BRANCH_KEYS:
        if key not in master.columns:
            master[key] = ""

    if "ratea" not in master.columns:
        master["ratea"] = None
    if "pflow_mm_max_allowable" in master.columns:
        fallback = pd.to_numeric(master["pflow_mm_max_allowable"], errors="coerce").abs()
        ratea = pd.to_numeric(master["ratea"], errors="coerce")
        master["rate_a"] = ratea.where(ratea > 0, fallback)
    else:
        master["rate_a"] = pd.to_numeric(master["ratea"], errors="coerce")
    master = _fill_canonical_column(master, "area", ["perf_mm_area", "pflow_area", "pflow_mm_area", "line_flt_cnt_area"])
    master = _fill_canonical_column(
        master,
        "voltage_class",
        ["perf_mm_voltage_class", "pflow_voltage_class", "pflow_mm_voltage_class", "line_flt_cnt_voltage_class"],
    )
    return master


def _fill_canonical_column(master, column: str, candidates: list[str]):
    if column not in master.columns:
        master[column] = ""
    for candidate in candidates:
        if candidate in master.columns:
            has_value = master[column].notna() & (master[column].astype(str).str.len() > 0)
            master[column] = master[column].where(has_value, master[candidate])
    return master


def _add_utilization_columns(pd, master):
    rate_a = _numeric_column(pd, master, "rate_a")
    base_flow = _numeric_column(pd, master, "pflow_mm_base_value")
    mean_flow = _numeric_column(pd, master, "pflow_average")
    min_flow = _numeric_column(pd, master, "pflow_mm_min_value")
    max_flow = _numeric_column(pd, master, "pflow_mm_max_value")

    worst_flow = max_flow.abs()
    worst_flow = pd.concat([min_flow.abs(), max_flow.abs()], axis=1).max(axis=1)

    master["base_flow_for_utilization"] = base_flow
    master["mean_n1_flow_for_utilization"] = mean_flow
    master["max_n1_flow_for_utilization"] = worst_flow
    master["base_case_utilization_pct"] = _safe_pct(base_flow.abs(), rate_a)
    master["mean_contingency_utilization_pct"] = _safe_pct(mean_flow.abs(), rate_a)
    master["max_contingency_utilization_pct"] = _safe_pct(worst_flow, rate_a)
    return master


def _numeric_column(pd, frame, column: str):
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series([None] * len(frame), index=frame.index, dtype="float64")


def _safe_pct(numerator, denominator):
    result = numerator / denominator * 100
    return result.where((denominator.notna()) & (denominator > 0))


def _add_outlier_reasons(master, threshold_pct: float):
    def reason(row) -> str:
        reasons = []
        for column in UTILIZATION_COLUMNS:
            value = row.get(column)
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed) and abs(parsed) > threshold_pct:
                reasons.append(f"{column}>{threshold_pct:g}")
        return "; ".join(reasons)

    master["outlier_reason"] = master.apply(reason, axis=1)
    return master
