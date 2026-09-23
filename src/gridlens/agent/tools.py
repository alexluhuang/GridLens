"""The deterministic tools the model calls instead of reading the result files itself.

Every public method decorated with `@tool` is exposed over MCP, and its docstring is the description the
model sees, so those docstrings are part of the interface rather than commentary. The decorator routes
each call through `ToolBase._invoke` in `gridlens.agent.tool_base`, which is where the shared behavior
lives: a per-call identifier, paging by offset and limit (limit=0 returns every row), a complete copy of
any result too large to send inline, provenance for every file read, stable error codes, and an
append-only audit record written before and after the call.

`ToolService` combines these analysis tools with the file tools in `gridlens.agent.file_tools` and the
GridLens operation tools in `gridlens.agent.gridlens_tools`, and `TOOL_NAMES` lists everything exposed
over MCP. Tools that read a run take `run_id` and an optional
`project`. A blank project means the project open in the session; otherwise it is a project folder path
or name, resolved by `gridlens.agent.session`. The analysis tools read the compact caches rather than a
run's multi-gigabyte flat result, and refuse a stale cache rather than quote numbers from it.

`rank` and `rank_groups` are the general loading tools: the model fills in which objects, which metric,
which statistic of a group, the order, how many, and which qualifiers remove objects, and the tool does
all of the sorting and arithmetic over every object in scope.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
import re
from typing import Literal, get_args
import xml.etree.ElementTree as ET

from gridlens.agent.file_tools import FILE_TOOL_NAMES, FileTools
from gridlens.agent.gridlens_tools import GRIDLENS_DESTRUCTIVE_TOOL_NAMES, GRIDLENS_TOOL_NAMES, GRIDLENS_WRITE_TOOL_NAMES, GridLensTools
from gridlens.agent.objects import (
    FACILITY_METRICS, FAMILIES, GROUP_DEFINITIONS, OBJECT_KINDS, ObjectField, ObjectFilter, ObjectGroup, ObjectKind,
    ObjectMetric, Order, check_conditions, check_fields, facility_record, group_labels, qualifies, reported, shown,
)
from gridlens.agent.policy import AgentError
from gridlens.agent.session import scoped_path
from gridlens.agent.tool_base import MAX_TABLE_ROWS, ToolBase, page_result, tool
from gridlens.analysis.branch_keys import canonical_branch_label
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.distribution_stats import GROUP_STATISTICS, STATISTIC_DEFINITIONS, GroupStatistic, group_statistic
from gridlens.analysis.loading import branch_key, max_line_utilization_rows
from gridlens.analysis.parser_models import PARSER_VERSION, ParsedTable
from gridlens.analysis.utilization import (
    TRANSFORMER_UTILIZATION_BRANCH_OPTIONS,
    UtilizationBranchOptions,
    selected_utilization_branch_types,
)


MAX_TABLE_BYTES = 64 * 1024 * 1024
Facility = Literal["line", "two_winding_transformer", "three_winding_transformer", "transformer_equivalent", "all"]
# The facility types each facility argument selects. "transformer" is every transformer kind, as the
# Transformer Analysis tab shows them.
FACILITY_OPTIONS = {
    "line": UtilizationBranchOptions(True, False, False, False),
    "two_winding_transformer": UtilizationBranchOptions(False, True, False, False),
    "three_winding_transformer": UtilizationBranchOptions(False, False, True, False),
    "transformer_equivalent": UtilizationBranchOptions(False, False, False, True),
    "transformer": TRANSFORMER_UTILIZATION_BRANCH_OPTIONS,
    "all": UtilizationBranchOptions(True, True, True, True),
}

ANALYSIS_TOOL_NAMES = (
    "rank", "rank_groups", "compare_runs", "rank_contingencies", "get_contingency_flows", "get_branch_contingencies",
    "propose_analysis_script",
)
TOOL_NAMES = ANALYSIS_TOOL_NAMES + FILE_TOOL_NAMES + GRIDLENS_TOOL_NAMES
# Tools that change something on disk or in Docker; every other tool only reads.
WRITE_TOOL_NAMES = GRIDLENS_WRITE_TOOL_NAMES | {"propose_analysis_script"}
DESTRUCTIVE_TOOL_NAMES = GRIDLENS_DESTRUCTIVE_TOOL_NAMES


def _number(value: object) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _descending(order: str) -> bool:
    """Return whether order sorts largest first, refusing anything but the two documented orders."""
    if order not in get_args(Order):
        raise AgentError("INVALID_ORDER", "Choose order='descending' or order='ascending'.")
    return order == "descending"


class AnalysisTools(ToolBase):
    """The analysis tools, bound to one session. The shared call machinery is in `ToolBase`."""

    def _csv(self, path: Path, run: Path) -> list[dict]:
        """Read one compact cache CSV inside run, refusing a file too large to be a GridLens cache."""
        self._source(path, run)
        if path.stat().st_size > MAX_TABLE_BYTES:
            raise AgentError("ARTIFACT_TOO_LARGE", "Rebuild compact analysis tables in the Analysis tab.")
        rows = []
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if len(rows) >= MAX_TABLE_ROWS or None in row or len(row) > 128:
                    raise AgentError("ARTIFACT_TOO_LARGE", "Rebuild compact analysis tables in the Analysis tab.")
                rows.append(row)
        return rows

    def _tables(self, run: Path) -> dict[str, ParsedTable]:
        """Read a run's fresh branch caches, or refuse with ANALYSIS_NOT_BUILT."""
        for manifest_name, directory in (("interactive_analysis_manifest.json", "interactive_tables"), ("analysis_manifest.json", "tables")):
            manifest_path = scoped_path(run, Path("reports") / manifest_name)
            if not manifest_path.exists():
                continue
            manifest = self._json(run, f"reports/{manifest_name}")
            if manifest.get("dataset_version") != ANALYSIS_DATASET_VERSION or manifest.get("parser_version") != PARSER_VERSION:
                continue
            tables = {}
            for name in ("pflow_mm", "branch_metadata", "area_metadata"):
                info = manifest.get("tables", {}).get(name, {})
                path = scoped_path(run, Path("reports") / directory / f"{name}.csv")
                source_name = info.get("source_file")
                if not source_name:
                    break
                source = scoped_path(run, Path("work") / source_name)
                if not path.exists() or not source.exists() or not source.stat().st_mtime_ns <= path.stat().st_mtime_ns <= manifest_path.stat().st_mtime_ns:
                    break
                self._source(source, run)
                rows = self._csv(path, run)
                tables[name] = ParsedTable(name, source_name, list(rows[0]) if rows else [], rows, info.get("notes", []))
            if len(tables) == 3:
                return tables
        raise AgentError("ANALYSIS_NOT_BUILT", "Build this run's analysis with run_analysis, or in Branch Analysis, Transformer Analysis, or the Agent tab, then ask again.")

    def _optional_table(self, run: Path, name: str) -> list[dict] | None:
        """Read an optional fresh cache or let its caller use a documented fallback."""
        path = scoped_path(run, f"reports/interactive_tables/{name}.csv")
        manifest_path = scoped_path(run, "reports/interactive_analysis_manifest.json")
        if not path.exists() or not manifest_path.exists():
            return None
        manifest = self._json(run, "reports/interactive_analysis_manifest.json")
        info = manifest.get("tables", {}).get(name)
        if not info or manifest.get("dataset_version") != ANALYSIS_DATASET_VERSION or manifest.get("parser_version") != PARSER_VERSION:
            return None
        source_name = info.get("source_file")
        if not source_name:
            return None
        source = scoped_path(run, Path("work") / source_name)
        if not source.exists() or not source.stat().st_mtime_ns <= path.stat().st_mtime_ns <= manifest_path.stat().st_mtime_ns:
            return None
        self._source(source, run)
        return self._csv(path, run)

    def _convergence(self, run: Path) -> dict:
        """Count a run's recorded cases and return the failed ones, from the CSV or success.txt."""
        work = scoped_path(run, "work", directory=True)
        paths = sorted(work.glob("*convergence*.csv"))
        if paths:
            rows = self._csv(paths[0], run)
            if rows and not {"event_idx", "contingency", "converged"}.issubset(rows[0]):
                raise AgentError("INVALID_ARTIFACT", "The convergence CSV has an unsupported schema.")
            failed = [row for row in rows if str(row.get("converged", "")).lower() not in ("true", "1") or row.get("status_code", "OK").upper() not in ("", "OK")]
        else:
            path = scoped_path(run, "work/success.txt")
            if not path.exists():
                self.warnings.append("Convergence information is unavailable; no claim of converged-only results can be made.")
                return {"known": False, "total": None, "converged": None, "failed": None, "rows": []}
            self._source(path, run)
            if path.stat().st_size > MAX_TABLE_BYTES:
                raise AgentError("ARTIFACT_TOO_LARGE", "The convergence artifact exceeds the read limit.")
            pattern = re.compile(r"contingency:\s*(\d+)\s+success:\s*(true|false)", re.I)
            rows = []
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    match = pattern.search(line)
                    if match:
                        rows.append({"event_idx": match[1], "converged": match[2].lower()})
                    if len(rows) > MAX_TABLE_ROWS:
                        raise AgentError("ARTIFACT_TOO_LARGE", "The convergence artifact exceeds the row limit.")
            failed = [row for row in rows if row["converged"] != "true"]
        if not rows:
            raise AgentError("INVALID_ARTIFACT", "No valid convergence records were found.")
        if failed:
            self.warnings.append(f"{len(failed)} of {len(rows)} recorded cases failed or were not converged; cached loading summaries do not exclude their rows.")
        return {"known": True, "total": len(rows), "converged": len(rows) - len(failed), "failed": len(failed), "rows": failed}

    def _xml_settings(self, run: Path, manifest: dict | None = None) -> dict[str, str | None]:
        """Read section-scoped XML settings from a run manifest for method and loading tools."""
        manifest = manifest if manifest is not None else self._json(run, "manifest.json")
        xml_name = manifest.get("xml_file")
        if not xml_name:
            return {}
        path = self._source(scoped_path(run, Path("work") / xml_name), run)
        if path.stat().st_size > 1024 * 1024:
            raise AgentError("ARTIFACT_TOO_LARGE", "The configuration XML exceeds the read limit.")
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        settings = {}
        unique = (
            "networkConfiguration_v33", "networkConfiguration_v34", "networkConfiguration",
            "minVoltage", "maxVoltage", "FullBranchN1", "FullGeneratorN1", "groupSize", "outputFormat",
        )
        scoped = (
            "Contingency_analysis/contingencyRating", "Contingency_analysis/contingencyList",
            "Contingency_analysis/monitorBranchesFile", "Contingency_analysis/monitorAreas",
            "Contingency_analysis/monitorKvMin", "Contingency_analysis/monitorKvMax",
            "Contingency_analysis/qlim", "Contingency_analysis/qlimDeadband", "Contingency_analysis/LTC",
            "Powerflow/initStart", "Powerflow/tolerance", "Powerflow/maxIteration",
            "Powerflow/qlim", "Powerflow/qlimDeadband", "Powerflow/LTC",
        )
        for name in unique:
            node = root.find(f".//{name}")
            if node is not None:
                settings[name] = node.text
        for name in scoped:
            node = root.find(f".//{name}")
            if node is not None:
                settings[name] = node.text
        return settings

    def _loading(self, run: Path, facility: str, area: str, min_kv: float, *, argument: tuple[str, str, str] | None = None) -> tuple[list[dict], dict, dict]:
        """Return filtered facility rows, convergence, and the scope used by loading tools.

        argument names the caller's facility parameter in warnings, as (name, value, value for every type);
        by default that is the loading tools' own facility parameter.
        """
        if facility not in FACILITY_OPTIONS or not math.isfinite(min_kv) or min_kv < 50:
            raise AgentError("INVALID_FILTER", "Choose a supported facility type and a minimum voltage of at least 50 kV (the GUI analysis cutoff).")
        parameter, chosen, everything = argument or ("facility", facility, "all")
        options = FACILITY_OPTIONS[facility]
        tables = self._tables(run)
        rows = max_line_utilization_rows(tables, options)
        summary = {branch_key(row): row for row in tables["pflow_mm"].rows}
        metadata = {branch_key(row): row for row in tables["branch_metadata"].rows}
        monitored = len(tables["pflow_mm"].rows)
        selected_types = selected_utilization_branch_types(options)
        excluded_facility = sum(
            str(metadata.get(branch_key(row), {}).get("raw_branch_type") or "nontransformer_branch") not in selected_types
            for row in tables["pflow_mm"].rows
        )
        below_cutoff = sum(
            max(_number(metadata.get(branch_key(row), {}).get("from_base_kv")) or 0,
                _number(metadata.get(branch_key(row), {}).get("to_base_kv")) or 0) < 50
            for row in tables["pflow_mm"].rows
        )
        try:
            configured_rating = self._xml_settings(run).get("Contingency_analysis/contingencyRating")
        except (ET.ParseError, OSError):
            configured_rating = None
            self.warnings.append("The configuration XML could not be read; the configured contingency rating is unknown.")
        filtered = []
        excluded_area = 0
        excluded_min_kv = 0
        legacy_rating = False
        for row in rows:
            if max(_number(row.get("from_base_kv")) or 0, _number(row.get("to_base_kv")) or 0) < min_kv:
                excluded_min_kv += 1
                continue
            details, branch = summary[branch_key(row)], metadata[branch_key(row)]
            if area and area.casefold() not in {str(value).casefold() for value in [*row["control_areas"], details.get("from_area"), details.get("to_area")]}:
                excluded_area += 1
                continue
            for name in ("base_utilization_pct", "mean_utilization_pct", "contingency_count", "overload_count"):
                row[name] = _number(details.get(name))
            source = str(details.get("utilization_source") or "legacy.pflow_mm")
            legacy_rating |= not source.startswith("csv_flat")
            # csv_flat caches record the lowest loading; legacy caches record the lowest MW flow instead.
            row["min_utilization_pct"] = _number(details.get("min_value")) if source.startswith("csv_flat") else None
            rating = _number(branch.get("rate_mva")) if source.startswith("csv_flat") else _number(branch.get("ratec"))
            if rating is not None and rating <= 0:
                rating = None
            if row["base_utilization_pct"] is None and not source.startswith("csv_flat") and rating:
                base_flow = _number(details.get("base_value"))
                if base_flow is not None:
                    row["base_utilization_pct"] = round(abs(base_flow) / rating * 100, 6)
            row.update(
                max_contingency_label=details.get("max_contingency_label", ""),
                thermal_margin_pct_points=round(100 - row["max_utilization_pct"], 6),
                rating_mva=rating, rating_basis="GridPACK reported loading_percent / rate_mva" if source.startswith("csv_flat") else "RAW rate C; legacy MW flow / MVA rating approximation",
                utilization_source=source,
                # Without a positive rating GridPACK reports 0% loading, which means unknown, not unloaded.
                utilization_known=rating is not None,
            )
            filtered.append(row)
        unrated = sum(1 for row in filtered if not row["utilization_known"])
        if unrated:
            self.warnings.append(f"{unrated} of {len(filtered)} facilities have no positive rating, so their reported utilization, often 0%, is unknown rather than low: it shows neither that they are unloaded nor an MVA margin. Rows with utilization_known false are these facilities.")
        convergence = self._convergence(run)
        convergence.pop("rows")
        if excluded_facility:
            self.warnings.append(f"{excluded_facility} of {monitored} monitored facilities were excluded by {parameter}='{chosen}'; use {parameter}='{everything}' to include supported types above the voltage cutoff.")
        if below_cutoff:
            noun = "facility is" if below_cutoff == 1 else "facilities are"
            self.warnings.append(f"{below_cutoff} monitored {noun} below the fixed 50 kV GridLens analysis cutoff and excluded for every facility filter.")
        if excluded_min_kv:
            self.warnings.append(f"{excluded_min_kv} facilities were excluded by min_kv={min_kv}.")
        if excluded_area:
            self.warnings.append(f"{excluded_area} facilities were excluded by area='{area}'.")
        if configured_rating is None:
            self.warnings.append("The configured contingency rating could not be established from the run XML.")
        elif legacy_rating and configured_rating.upper() != "C":
            self.warnings.append(f"The run configured contingencyRating={configured_rating}, but the legacy pflow_mm approximation divides by RAW rate C; those utilizations are not on the configured rating basis.")
        self.warnings.extend([
            "Maximum observed loading includes all rows in the cache, including the base case; it is not a converged N-1-only metric.",
            "Thermal margin is 100 minus maximum utilization, in percentage points. It is not available transfer, generation, or load-serving capacity.",
            "contingency_count counts recorded loading rows (including base); overload_count counts loading >=100% or a reported violation flag.",
        ])
        scope = {"filters": {"facility": facility, "min_kv": min_kv, "area": area}, "monitored_facility_count": monitored, "analyzed_facility_count": len(filtered), "configured_contingency_rating": configured_rating}
        return filtered, convergence, scope

    def _objects(self, run_id: str, project: str, kind: str, metric: str, filters: list | None) -> tuple[list[dict], dict]:
        """Return every object in scope that meets the qualifiers and has a known metric value, and the counts behind them.

        The objects are the facilities the GUI charts use: those of the chosen kind at or above the 50 kV cutoff.
        """
        if kind not in OBJECT_KINDS:
            raise AgentError("INVALID_OBJECT", "Choose object='branches', 'transformers', or 'both'.")
        if metric not in FACILITY_METRICS:
            raise AgentError("INVALID_METRIC", f"Choose a metric from: {', '.join(FACILITY_METRICS)}.")
        conditions = check_conditions(kind, filters)
        rows, convergence, scope = self._loading(self._run(run_id, project), OBJECT_KINDS[kind], "", 50.0, argument=("object", kind, "both"))
        records = [facility_record(row) for row in rows]
        kept = [record for record in records if qualifies(record, conditions)]
        known = [record for record in kept if record["values"][metric] is not None]
        if len(known) < len(kept):
            self.warnings.append(f"{len(kept) - len(known)} objects have no known {metric}, because they have no positive rating or the cache does not record it, and were left out.")
        if metric == "min_utilization_pct" and known:
            zero = sum(1 for record in known if record["values"][metric] == 0)
            self.warnings.append(f"{zero} of {len(known)} objects have a minimum loading of 0%, usually in the case where the object itself is out of service; a low minimum does not show light loading.")
        counts = {
            "monitored_facility_count": scope["monitored_facility_count"], "objects_in_scope": len(records),
            "excluded_by_filters": len(records) - len(kept), "excluded_unknown_value": len(kept) - len(known),
            "configured_contingency_rating": scope["configured_contingency_rating"],
            "rating_basis": sorted({record["rating_basis"] for record in known}), "convergence": convergence,
        }
        return known, counts

    @tool
    def rank(self, run_id: str, object: ObjectKind = "branches", order: Order = "descending", metric: ObjectMetric = "max_utilization_pct", magnitude: int = 10, filters: list[ObjectFilter] | None = None, fields: list[ObjectField] | None = None, project: str = "") -> dict:
        """Sort objects by one metric over every object in scope and return the first `magnitude` (0 returns all), each with the value it was sorted by.

        object is branches (non-transformer), transformers (every kind), or both, at or above 50 kV. metric is a per-object value over all recorded cases: max_utilization_pct (congestion), base_utilization_pct, mean_utilization_pct, min_utilization_pct, thermal_margin_pct_points, overload_count, contingency_count, rating_mva, or nominal_kv. filters remove objects that fail any qualifier, e.g. [{"column": "control_area", "op": "==", "value": "Coast"}, {"column": "max_utilization_pct", "op": ">", "value": 100}]; total_matching counts every object that remains. fields adds those attributes to each row, such as ["control_area", "binding_contingency", "base_utilization_pct"]. For counts, means, or any other statistic use rank_groups, never these rows.
        """
        descending = _descending(order)
        extra = check_fields(object, fields)
        objects, counts = self._objects(run_id, project, object, metric, filters)
        objects.sort(key=lambda record: (-record["values"][metric] if descending else record["values"][metric], tuple(str(record["identity"][name]) for name in ("from_bus", "to_bus", "line_id", "section"))))
        rows = [
            {"rank": position, **record["identity"], "value": reported(record["values"][metric]), **{name: shown(record["fields"][name]) for name in extra}}
            for position, record in enumerate(objects, 1)
        ]
        units, definition, _ = FACILITY_METRICS[metric]
        return {
            "object": object, "metric": metric, "order": order, "units": units, "definition": definition, "filters": filters or [], **counts,
            **page_result(rows[:magnitude] if magnitude else rows, len(rows), 0, magnitude),
        }

    @tool
    def rank_groups(self, run_id: str, group: ObjectGroup = "voltage_class", object: ObjectKind = "branches", order: Order = "descending", metric: ObjectMetric = "max_utilization_pct", statistic: GroupStatistic = "mean", magnitude: int = 10, filters: list[ObjectFilter] | None = None, project: str = "") -> dict:
        """Sort groups by one statistic of one metric over all of each group's objects and return the first `magnitude` groups (0 returns all), each with that statistic and the count of objects it used.

        group is control_area (an object joining two areas counts in both), voltage_class (the voltage groups or categories of the Branch Analysis tab, such as 100-229 kV; transformers group by step direction), nominal_kv (each exact base voltage, such as 138 kV), branch_type, or binding_contingency (the case that set each object's maximum loading). statistic is mean, median, min, max, std, var (population), iqr, or count. metric is a per-object value as in rank, so statistic='mean' of metric='max_utilization_pct' is the mean maximum loading the Branch Analysis tab shows, and of mean_utilization_pct or min_utilization_pct it is the mean mean or mean min. object and filters are as in rank; filters remove objects before grouping.
        """
        if group not in FAMILIES["facility"]["groups"]:
            raise AgentError("INVALID_GROUP", f"Choose a group from: {', '.join(FAMILIES['facility']['groups'])}.")
        if statistic not in GROUP_STATISTICS:
            raise AgentError("INVALID_STATISTIC", f"Choose a statistic from: {', '.join(GROUP_STATISTICS)}.")
        descending = _descending(order)
        objects, counts = self._objects(run_id, project, object, metric, filters)
        members: dict[str, list[float]] = {}
        for record in objects:
            for label in group_labels(record["fields"], group):
                members.setdefault(label, []).append(record["values"][metric])
        groups = [(label, group_statistic(values, statistic), len(values)) for label, values in members.items()]
        groups.sort(key=lambda item: (-item[1] if descending else item[1], item[0]))
        rows = [{"rank": position, "group": label, "value": reported(value), "count": count} for position, (label, value, count) in enumerate(groups, 1)]
        units, definition, _ = FACILITY_METRICS[metric]
        return {
            "group": group, "object": object, "metric": metric, "statistic": statistic, "order": order,
            "units": "objects" if statistic == "count" else f"{units}²" if statistic == "var" else units,
            "definitions": {"group": GROUP_DEFINITIONS[group], "metric": definition, "statistic": STATISTIC_DEFINITIONS[statistic], "count": "the objects each group's value was computed from"},
            "filters": filters or [], **counts, "objects_used": len(objects),
            **page_result(rows[:magnitude] if magnitude else rows, len(rows), 0, magnitude),
        }

    @tool
    def compare_runs(self, run_id: str, other_run_id: str, facility: Facility = "line", limit: int = 10, offset: int = 0, project: str = "", other_project: str = "") -> dict:
        """Align full branch keys for two completed runs and rank maximum-loading increases (other minus run), in percentage points."""
        first_run = self._run(run_id, project)
        second_run = self._run(other_run_id, other_project)
        if first_run == second_run:
            raise AgentError("INVALID_COMPARISON", "Select two different completed runs.")
        first, first_convergence, first_scope = self._loading(first_run, facility, "", 50.0)
        second, second_convergence, second_scope = self._loading(second_run, facility, "", 50.0)
        left, right = {branch_key(row): row for row in first}, {branch_key(row): row for row in second}
        rows = []
        for key in left.keys() & right.keys():
            a, b = left[key], right[key]
            rows.append({"from_bus": key[0], "to_bus": key[1], "line_id": key[2], "section": key[3], "first_max_pct": a["max_utilization_pct"], "second_max_pct": b["max_utilization_pct"], "delta_pct_points": round(b["max_utilization_pct"] - a["max_utilization_pct"], 6), "rating_changed": (a["rating_mva"], a["rating_basis"]) != (b["rating_mva"], b["rating_basis"])})
        rows.sort(key=lambda row: (-row["delta_pct_points"], tuple(str(item) for item in branch_key(row))))
        self.warnings.append("Compare dispatch, topology, contingency coverage, and rating changes before interpreting loading differences.")
        return {"rows": rows, "first_only": len(left.keys() - right.keys()), "second_only": len(right.keys() - left.keys()), "first_convergence": first_convergence, "second_convergence": second_convergence, "first_scope": first_scope, "second_scope": second_scope}

    @tool
    def rank_contingencies(self, run_id: str, metric: Literal["max_loading_pct", "violation_count"] = "max_loading_pct", converged_only: bool = True, limit: int = 10, offset: int = 0, project: str = "") -> dict:
        """Rank non-base contingencies from the compact cache, excluding failed/unknown cases by default. Counts are monitored rows."""
        if metric not in ("max_loading_pct", "violation_count"):
            raise AgentError("INVALID_METRIC", "Choose maximum loading or violation count.")
        rows = self._optional_table(self._run(run_id, project), "contingency_summary")
        if rows is None:
            raise AgentError("ANALYSIS_NOT_BUILT", "Rebuild the analysis with run_analysis(rebuild=True), or with Build / refresh analysis in the Agent tab, to create the contingency summary.")
        candidates = [row for row in rows if _number(row.get("event_idx")) != 0]
        converged = [row for row in candidates if str(row.get("converged")).lower() in ("true", "1") and row.get("status_code", "").upper() in ("", "OK")]
        selected = converged if converged_only else candidates
        selected = [{**row, "event_idx": int(row["event_idx"]), "max_loading_pct": _number(row["max_loading_pct"]), "violation_count": int(row["violation_count"]), "monitored_facility_count": int(row["monitored_facility_count"])} for row in selected]
        selected.sort(key=lambda row: (-(row[metric] or 0), row["event_idx"], row["contingency"]))
        self.warnings.append("Violations count loading >=100% or a reported violation flag. Counts cover recorded monitored rows only.")
        if not converged_only:
            self.warnings.append("This ranking includes failed or unknown convergence states; inspect the convergence fields.")
        return {"rows": selected, "metric": metric, "units": "%" if metric == "max_loading_pct" else "monitored rows", "recorded_contingencies": len(candidates), "converged_contingencies": len(converged), "excluded_failed_or_unknown": len(candidates) - len(converged) if converged_only else 0}

    def _indexed_rows(self, run: Path, *, event_idx=None, branch=None, offset=0, limit=10) -> dict:
        """Query a run's Parquet event index for one contingency or one branch key.

        The index returns the highest-loading rows up to the end of the requested page, or every row
        when limit is 0, and `_invoke` then cuts the page from them.
        """
        from gridlens.analysis.event_index import query_event_index

        manifest = scoped_path(run, "reports/event_index/manifest.json")
        if not manifest.exists():
            raise AgentError("INDEX_NOT_BUILT", "Build the index with run_analysis(include_index=True), or with Include contingency drill-down index and Build / refresh analysis in the Agent tab.")
        try:
            rows, total, paths = query_event_index(run, event_idx=event_idx, branch=branch, limit=offset + limit if limit else 0)
        except AgentError:
            raise
        except ValueError as exc:
            raise AgentError("INDEX_STALE", "Rebuild the index with run_analysis(include_index=True, rebuild=True), or in the Agent tab.") from exc
        if branch is not None and total == 0 and branch in {branch_key(row) for row in self._tables(run)["pflow_mm"].rows}:
            raise AgentError("KEY_NOT_INDEXED", "This cached branch is absent from the drill-down index; rebuild both analysis and index.")
        for path in paths:
            self._source(path, run)
        convergence = self._convergence(run)
        failed = {str(row["event_idx"]) for row in convergence.pop("rows")}
        for row in rows:
            row["convergence"] = "failed" if str(row["event_idx"]) in failed else "see convergence source" if convergence["known"] else "unknown"
        self.warnings.append("Rows are ranked by absolute recorded loading, including base and non-converged cases. A single case does not establish transfer capability.")
        return {"rows": rows, "total_matching": total, "convergence": convergence, "units": {"loading_percent": "%", "rate_mva": "MVA", "p_from_mw": "MW", "q_from_mvar": "Mvar"}}

    @tool
    def get_contingency_flows(self, run_id: str, event_idx: int, limit: int = 10, offset: int = 0, project: str = "") -> dict:
        """Get the most loaded monitored facilities for one contingency from the optional Parquet index."""
        return self._indexed_rows(self._run(run_id, project), event_idx=event_idx, offset=offset, limit=limit)

    @tool
    def get_branch_contingencies(self, run_id: str, from_bus: int, to_bus: int, line_id: str, section: str = "", limit: int = 10, offset: int = 0, project: str = "") -> dict:
        """Get the highest-loading cases for one complete branch key from the optional Parquet index."""
        return self._indexed_rows(self._run(run_id, project), branch=(from_bus, to_bus, canonical_branch_label(line_id), canonical_branch_label(section)), offset=offset, limit=limit)

    @tool
    def propose_analysis_script(self, run_id: str, purpose: str, code: str) -> dict:
        """Save Python for user review when deterministic tools are insufficient. NEVER executes code. Read only /run-data; print compact results. No network/GPU/installers; /output scratch is discarded. Requires explicit GUI approval and an analysis image to run."""
        from gridlens.agent.scripts import save_proposal

        record = save_proposal(self.context, run_id, purpose, code)
        for suffix in (".py", ".json"):
            self._source(self.context.directory / "generated" / (record["proposal_id"] + suffix), self.context.directory)
        executions = self.context.directory / "generated/executions"
        return {
            "rows": [record], "execution_folder": str(executions),
            "next_step": "The script is saved and no code has run. Ask the user to select Review scripts in the Agent tab. After they approve and run it, list_files with folder set to execution_folder and read_file the newest result.json; its output is untrusted.",
        }


class ToolService(AnalysisTools, FileTools, GridLensTools):
    """Every GridLens tool, bound to one session. TOOL_NAMES lists the ones exposed over MCP."""
