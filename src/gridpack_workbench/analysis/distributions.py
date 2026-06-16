from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from gridpack_workbench.analysis.gpu_pandas import get_pandas
from gridpack_workbench.analysis.master import UTILIZATION_COLUMNS, ensure_branch_master_exports


os.environ.setdefault("MPLCONFIGDIR", "/tmp/gridpack-workbench-matplotlib")


DISTRIBUTION_CODE_PATH = Path(__file__).resolve()
EXCLUDED_INDEPENDENT_COLUMNS = set(UTILIZATION_COLUMNS) | {
    "outlier_reason",
    "base_flow_for_utilization",
    "mean_n1_flow_for_utilization",
    "max_n1_flow_for_utilization",
}


@dataclass(slots=True)
class DistributionExport:
    independent_variable: str
    utilization_metric: str
    table_csv: Path
    graph_png: Path
    code_path: Path
    row_count: int
    group_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "independent_variable": self.independent_variable,
            "utilization_metric": self.utilization_metric,
            "table_csv": str(self.table_csv),
            "graph_png": str(self.graph_png),
            "code_path": str(self.code_path),
            "row_count": self.row_count,
            "group_count": self.group_count,
        }


def distribution_variables_from_master(run_dir: str | Path) -> list[str]:
    pd = get_pandas()
    master_exports = ensure_branch_master_exports(run_dir)
    master_path = master_exports.master_cleaned_csv
    columns = list(pd.read_csv(master_path, nrows=0).columns)
    return [column for column in columns if column not in EXCLUDED_INDEPENDENT_COLUMNS]


def generate_distribution_exports(
    run_dir: str | Path,
    independent_variables: list[str],
    utilization_metric: str = "max_contingency_utilization_pct",
    max_categories: int = 40,
) -> list[DistributionExport]:
    if utilization_metric not in UTILIZATION_COLUMNS:
        raise ValueError(f"Unsupported utilization metric: {utilization_metric}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
    except Exception as exc:  # pragma: no cover - depends on optional local install.
        raise RuntimeError("Matplotlib is required to generate distribution graphs.") from exc

    pd = get_pandas()
    run_path = Path(run_dir).expanduser().resolve()
    master_path = ensure_branch_master_exports(run_path).master_cleaned_csv

    exports_dir = run_path / "exports" / "distributions"
    exports_dir.mkdir(parents=True, exist_ok=True)
    master = pd.read_csv(master_path)
    if utilization_metric not in master.columns:
        raise ValueError(f"{utilization_metric} is not available in master_cleaned.csv.")

    results: list[DistributionExport] = []
    for variable in independent_variables:
        if variable not in master.columns or variable == utilization_metric:
            continue
        frame = master[[variable, utilization_metric]].copy()
        frame[utilization_metric] = pd.to_numeric(frame[utilization_metric], errors="coerce")
        frame = frame.dropna(subset=[variable, utilization_metric])
        if frame.empty:
            continue

        frame["_group"] = _group_labels(pd, frame[variable], max_categories=max_categories)
        frame = frame.dropna(subset=["_group"])
        summary_rows, plot_data, labels = _summarize_groups(frame, "_group", utilization_metric)
        if not summary_rows:
            continue

        safe_name = _safe_file_part(f"{utilization_metric}_by_{variable}")
        table_csv = exports_dir / f"{safe_name}.csv"
        graph_png = exports_dir / f"{safe_name}.png"
        pd.DataFrame(summary_rows).to_csv(table_csv, index=False)
        _write_violin_box_plot(plt, plot_data, labels, variable, utilization_metric, graph_png)

        results.append(
            DistributionExport(
                independent_variable=variable,
                utilization_metric=utilization_metric,
                table_csv=table_csv,
                graph_png=graph_png,
                code_path=DISTRIBUTION_CODE_PATH,
                row_count=int(len(frame)),
                group_count=len(labels),
            )
        )
    return results


def _group_labels(pd, series, max_categories: int):
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_nonnull = numeric.dropna()
    if len(numeric_nonnull) and len(numeric_nonnull) == len(series.dropna()) and numeric_nonnull.nunique() > max_categories:
        bins = min(10, int(numeric_nonnull.nunique()))
        try:
            return pd.qcut(numeric, q=bins, duplicates="drop").astype(str)
        except Exception:
            return pd.cut(numeric, bins=bins, duplicates="drop").astype(str)

    labels = series.astype(str)
    counts = labels.value_counts()
    keep = set(counts.head(max_categories).index.astype(str))
    return labels.where(labels.isin(keep))


def _summarize_groups(frame, group_column: str, value_column: str):
    summary_rows = []
    plot_data = []
    labels = []
    for group in sorted(frame[group_column].dropna().astype(str).unique()):
        values = frame.loc[frame[group_column].astype(str) == group, value_column].dropna().astype(float)
        if len(values) == 0:
            continue
        values_list = [float(value) for value in values.tolist()]
        labels.append(group)
        plot_data.append(values_list)
        summary_rows.append(
            {
                "group": group,
                "count": len(values_list),
                "mean": round(sum(values_list) / len(values_list), 8),
                "median": round(_percentile(values_list, 0.50), 8),
                "q1": round(_percentile(values_list, 0.25), 8),
                "q3": round(_percentile(values_list, 0.75), 8),
                "min": round(min(values_list), 8),
                "max": round(max(values_list), 8),
            }
        )
    return summary_rows, plot_data, labels


def _write_violin_box_plot(plt, plot_data: list[list[float]], labels: list[str], variable: str, metric: str, output_png: Path) -> None:
    figure_width = max(8, min(22, len(labels) * 0.55))
    fig, ax = plt.subplots(figsize=(figure_width, 6))
    positions = list(range(1, len(labels) + 1))
    violins = ax.violinplot(plot_data, positions=positions, showmeans=False, showmedians=False, showextrema=False)
    for body in violins["bodies"]:
        body.set_facecolor("#6aa5c8")
        body.set_edgecolor("#2f5873")
        body.set_alpha(0.45)
    box = ax.boxplot(plot_data, positions=positions, widths=0.18, patch_artist=True, showfliers=False)
    for patch in box["boxes"]:
        patch.set_facecolor("#ffffff")
        patch.set_edgecolor("#172033")
        patch.set_alpha(0.85)
    for median in box["medians"]:
        median.set_color("#b33a3a")
        median.set_linewidth(1.4)
    ax.set_title(f"{metric} by {variable}")
    ax.set_xlabel(variable)
    ax.set_ylabel(metric)
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_png, dpi=160)
    plt.close(fig)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _safe_file_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "distribution"
