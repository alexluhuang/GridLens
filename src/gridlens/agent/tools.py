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

`rank` and `rank_groups` are the analysis tools: the model fills in which objects (facilities,
contingencies, or cases), which metric, which statistic of a group, the order, how many, which qualifiers
remove objects, and optionally a run to compare with, and the tool does all of the sorting and arithmetic
over every object in scope. The vocabulary those parameters take is in `gridlens.agent.objects`.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
import re
from typing import get_args
import xml.etree.ElementTree as ET

from gridlens.agent.file_tools import FILE_TOOL_NAMES, FileTools
from gridlens.agent.gridlens_tools import GRIDLENS_DESTRUCTIVE_TOOL_NAMES, GRIDLENS_TOOL_NAMES, GRIDLENS_WRITE_TOOL_NAMES, GridLensTools
from gridlens.agent.objects import (
    BASE_CASE, CASE_INDEX_COLUMNS, CONTINGENCY_ATTRIBUTES, FACILITY_ATTRIBUTES, GROUP_DEFINITIONS, OBJECT_KINDS,
    ObjectField, ObjectFilter, ObjectGroup, ObjectKind, ObjectMetric, Order,
    case_record, change_units, check_conditions, check_fields, check_group, check_values, contingency_record, facility_fields,
    facility_label, facility_record, group_labels, metric_units, qualifies, reported, resolve_metric, shown,
)
from gridlens.agent.policy import AgentError
from gridlens.agent.session import scoped_path
from gridlens.agent.tool_base import MAX_TABLE_ROWS, ToolBase, page_result, tool
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.distribution_stats import GROUP_STATISTICS, STATISTIC_DEFINITIONS, GroupStatistic, group_statistic
from gridlens.analysis.event_index import case_key
from gridlens.analysis.loading import bus_area_labels, facility_attributes, max_line_utilization_rows, branch_key
from gridlens.analysis.parser_models import PARSER_VERSION, ParsedTable
from gridlens.analysis.utilization import (
    TRANSFORMER_UTILIZATION_BRANCH_OPTIONS,
    UtilizationBranchOptions,
    selected_utilization_branch_types,
)


MAX_TABLE_BYTES = 64 * 1024 * 1024
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

ANALYSIS_TOOL_NAMES = ("rank", "rank_groups", "propose_analysis_script")
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


# Contingency metrics from the compact summary, which a contingency whose solution failed has no rows for.
SUMMARY_METRICS = ("max_loading_pct", "overload_count", "monitored_facility_count")


def _require_metrics(missing: list[str], used: set[str], run: Path) -> None:
    """Refuse a call that needs a metric the run's analysis cache was built without."""
    needed = sorted(set(missing) & used)
    if needed:
        raise AgentError("CACHE_FIELD_UNAVAILABLE", f"Run {run.name}'s analysis cache was built before {', '.join(needed)} was recorded. Rebuild it with run_analysis(rebuild=True), then ask again.")


def _descending(order: str) -> bool:
    """Return whether order sorts largest first, refusing anything but the two documented orders."""
    if order not in get_args(Order):
        raise AgentError("INVALID_ORDER", "Choose order='descending' or order='ascending'.")
    return order == "descending"


def _key(record: dict) -> tuple:
    """Return a facility record's full branch key."""
    return tuple(record["identity"][name] for name in ("from_bus", "to_bus", "line_id", "section"))


def _order(record: dict) -> tuple:
    """Order objects with equal values by their identity: the full branch key, or the event."""
    return tuple((0, value, "") if isinstance(value, int) else (1, 0, str(value)) for name, value in record["identity"].items() if name not in ("object", "contingency"))


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
            for name in ("base_utilization_pct", "mean_utilization_pct", "contingency_count"):
                row[name] = _number(details.get(name))
            # The cache's overload_count also counts GridPACK's viol flag, which marks the outaged branch itself.
            row["overload_count"] = _number(details.get("thermal_overload_count"))
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
            "contingency_count counts recorded loading rows (including base); overload_count counts those at or above 100% loading.",
        ])
        scope = {"filters": {"facility": facility, "min_kv": min_kv, "area": area}, "monitored_facility_count": monitored, "analyzed_facility_count": len(filtered), "configured_contingency_rating": configured_rating}
        # A cache built before thermal counts were added has only the flag-inclusive one, which is not offered.
        scope["missing_metrics"] = [] if "thermal_overload_count" in tables["pflow_mm"].columns else ["overload_count"]
        return filtered, convergence, scope

    def _convergence_rows(self, run: Path) -> list[dict] | None:
        """Return a run's convergence records from its convergence CSV or success.txt, or None when it has neither."""
        work = scoped_path(run, "work", directory=True)
        paths = sorted(work.glob("*convergence*.csv"))
        if paths:
            rows = self._csv(paths[0], run)
            if rows and not {"event_idx", "contingency", "converged"}.issubset(rows[0]):
                raise AgentError("INVALID_ARTIFACT", "The convergence CSV has an unsupported schema.")
        else:
            path = scoped_path(run, "work/success.txt")
            if not path.exists():
                return None
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
        if not rows:
            raise AgentError("INVALID_ARTIFACT", "No valid convergence records were found.")
        return rows

    def _convergence(self, run: Path) -> dict:
        """Count a run's recorded cases and return the failed ones, for the caveats every loading result carries."""
        rows = self._convergence_rows(run)
        if rows is None:
            self.warnings.append("Convergence information is unavailable; no claim of converged-only results can be made.")
            return {"known": False, "total": None, "converged": None, "failed": None, "rows": []}
        failed = [row for row in rows if str(row.get("converged", "")).lower() not in ("true", "1") or str(row.get("status_code") or "OK").upper() != "OK"]
        if failed:
            self.warnings.append(f"{len(failed)} of {len(rows)} recorded cases failed or were not converged; cached loading summaries do not exclude their rows.")
        return {"known": True, "total": len(rows), "converged": len(rows) - len(failed), "failed": len(failed), "rows": failed}

    def _facilities(self, run: Path, kind: str) -> tuple[list[dict], dict, list[str]]:
        """Return a run's facility records of kind, at or above the 50 kV cutoff, the counts that go with them, and the metrics its cache lacks."""
        rows, convergence, scope = self._loading(run, OBJECT_KINDS[kind], "", 50.0, argument=("object", kind, "both"))
        counts = {"monitored_facility_count": scope["monitored_facility_count"], "configured_contingency_rating": scope["configured_contingency_rating"], "convergence": convergence}
        return [facility_record(row) for row in rows], counts, scope["missing_metrics"]

    def _compared(self, run: Path, records: list[dict], kind: str, metric: str, compare_run_id: str, compare_project: str) -> tuple[list[dict], dict]:
        """Keep the records whose facility is also in the compare run, each with its change in metric, compare run minus this run."""
        other_run = self._run(compare_run_id, compare_project)
        if other_run == run:
            raise AgentError("INVALID_COMPARISON", "Name a different run to compare with.")
        before = len(self.warnings)
        others, _, missing = self._facilities(other_run, kind)
        _require_metrics(missing, {metric}, other_run)
        self.warnings[before:] = [f"In compare run {other_run.name}: {warning}" for warning in self.warnings[before:]]
        by_key = {_key(record): record for record in others}
        matched = []
        for record in records:
            other = by_key.get(_key(record))
            if other is None:
                continue
            first, second = record["values"][metric], other["values"][metric]
            change = second - first if first is not None and second is not None else None
            record["fields"].update(compare_value=second, change=change, rating_changed=record["values"]["rating_mva"] != other["values"]["rating_mva"])
            record["values"]["change"] = change
            matched.append(record)
        self.warnings.append("Compare dispatch, topology, contingency coverage, and rating changes before interpreting loading differences.")
        own = {_key(record) for record in records}
        return matched, {
            "compare_run_id": other_run.name, "only_in_run": len(records) - len(matched), "only_in_compare_run": len(set(by_key) - own),
            "rating_changed_count": sum(1 for record in matched if record["fields"]["rating_changed"]),
        }

    def _contingencies(self, run: Path, facilities: dict | None = None) -> tuple[list[dict], list[str]]:
        """Return a run's contingency records, from its compact summary and convergence file, without the base case, and the metrics its summary lacks."""
        summary = self._optional_table(run, "contingency_summary")
        convergence = self._convergence_rows(run) or []
        if facilities is None:
            try:
                facilities = facility_attributes(self._tables(run))
            except AgentError:
                facilities = {}
        bus_areas: dict = {}
        for key, attributes in facilities.items():
            for bus, area in zip(key[:2], attributes["end_areas"]):
                if area != "unknown":
                    bus_areas.setdefault(bus, area)
        # A generator's terminal bus is often at the end of no monitored facility; the bus table names every bus's area.
        for bus, area in bus_area_labels(self._optional_table(run, "bus_metadata") or []).items():
            bus_areas.setdefault(bus, area)
        summaries = {int(event): row for row in summary or [] if (event := _number(row.get("event_idx"))) is not None}
        solutions = {int(event): row for row in convergence if (event := _number(row.get("event_idx"))) is not None}
        if summary is None:
            self.warnings.append("This run has no current contingency summary, so max_loading_pct, overload_count, and monitored_facility_count are unknown. Rebuild the analysis with run_analysis(rebuild=True) to add them.")
        if not convergence:
            self.warnings.append("This run has no convergence file, so no contingency is known to have converged.")
        missing = ["overload_count"] if summary and "thermal_overload_count" not in summary[0] else []
        return [contingency_record(event, summaries.get(event, {}), solutions.get(event, {}), bus_areas, facilities) for event in sorted(set(summaries) | set(solutions)) if event != 0], missing

    def _population(self, run: Path, kind: str, family: str, metric: str, conditions: list, *, group: str = "", fields: tuple = (), compare_run_id: str = "", compare_project: str = "", unknown_values: str = "exclude") -> tuple[list[dict], dict, str]:
        """Return the facilities or contingencies that meet the qualifiers, the counts behind them, and their value's key.

        fields are the extra fields the caller returns. unknown_values says what happens to an object with no
        known value: "exclude" leaves it out, as a statistic must; "count" keeps it, since a count needs no
        value; and "list" keeps it for rank to list after the ranked objects.
        """
        value_key = metric
        used = {metric, *fields, *(column for column, _, _ in conditions)}
        if family == "facility":
            records, counts, missing = self._facilities(run, kind)
            _require_metrics(missing, used, run)
            check_values(records, conditions, "facility", self.warnings)
            if compare_run_id:
                records, compared = self._compared(run, records, kind, metric, compare_run_id, compare_project)
                counts.update(compared)
                value_key = "change"
        else:
            records, missing = self._contingencies(run)
            _require_metrics(missing, used, run)
            check_values(records, conditions, "contingency", self.warnings)
            counts = {"recorded_contingencies": len(records)}
            # Ranking a failed solution as severe would mislead, so only converged contingencies count unless asked.
            if not ({column for column, _, _ in conditions} | {group}) & {"converged", "status_code"}:
                converged = [record for record in records if record["fields"]["converged"] == "true"]
                if len(converged) < len(records):
                    self.warnings.append(f"Only converged contingencies are included: {len(records) - len(converged)} of {len(records)} failed or have unknown convergence and were left out. Qualify on converged or status_code to include them.")
                counts["excluded_not_converged"] = len(records) - len(converged)
                records = converged
        kept = [record for record in records if qualifies(record, conditions)]
        known = [record for record in kept if record["values"][value_key] is not None]
        unknown = len(kept) - len(known)
        if unknown and unknown_values != "count":
            if family == "facility":
                reason = ", because they have no positive rating or the cache does not record it,"
            elif value_key in SUMMARY_METRICS:
                reason = ", because a contingency whose solution failed records no flows,"
            else:
                reason = ""
            fate = "were left out" if unknown_values == "exclude" else "are listed after the ranked objects, with value null"
            self.warnings.append(f"{unknown} objects have no known {value_key}{reason} and {fate}.")
        if metric == "min_utilization_pct" and known:
            zero = sum(1 for record in known if record["values"][metric] == 0)
            self.warnings.append(f"{zero} of {len(known)} objects have a minimum loading of 0%, usually in the case where the object itself is out of service; a low minimum does not show light loading.")
        counts.update(objects_in_scope=len(records), excluded_by_filters=len(records) - len(kept))
        counts["without_value" if unknown_values == "list" else "excluded_unknown_value"] = unknown if unknown_values != "count" else 0
        if family == "facility":
            counts["rating_basis"] = sorted({record["rating_basis"] for record in known})
        return (known if unknown_values == "exclude" else kept), counts, value_key

    def _cases(self, run: Path, conditions: list, used: set[str]) -> dict:
        """Resolve case qualifiers into the events and facilities they select and the numeric qualifiers the index applies.

        used names the fields and group of the call, so contingency caveats are kept only when they matter.
        """
        from gridlens.analysis.event_index import open_event_index

        if not scoped_path(run, "reports/event_index/manifest.json").exists():
            raise AgentError("INDEX_NOT_BUILT", "Build the drill-down index with run_analysis(include_index=True), or with Include contingency drill-down index and Build / refresh analysis in the Agent tab.")
        # Check the index before the caches, so a changed flat result is reported against the index.
        self._index(run, open_event_index)
        facilities = facility_attributes(self._tables(run))
        before = len(self.warnings)
        contingencies = {record["fields"]["event_idx"]: record for record in self._contingencies(run, facilities)[0]}
        if not ({column for column, _, _ in conditions} | used) & (set(CONTINGENCY_ATTRIBUTES) - {"event_idx", "contingency"}):
            del self.warnings[before:]
        facility_conditions = [condition for condition in conditions if condition[0] in FACILITY_ATTRIBUTES]
        contingency_conditions = [condition for condition in conditions if condition[0] in CONTINGENCY_ATTRIBUTES]
        check_values([{"fields": facility_fields(key, attributes)} for key, attributes in facilities.items()], facility_conditions, "facility", self.warnings)
        check_values([BASE_CASE, *contingencies.values()], contingency_conditions, "contingency", self.warnings)
        keys = events = None
        if facility_conditions:
            keys = {case_key(*key) for key, attributes in facilities.items() if qualifies({"fields": facility_fields(key, attributes)}, facility_conditions)}
        if contingency_conditions:
            events = {event for event, record in {0: BASE_CASE, **contingencies}.items() if qualifies(record, contingency_conditions)}
        return {
            "facilities": facilities, "contingencies": contingencies, "keys": keys, "events": events,
            "index_conditions": [condition for condition in conditions if condition[0] in CASE_INDEX_COLUMNS],
        }

    def _index(self, run: Path, query, **arguments):
        """Run one drill-down index query, turning its failures into the errors the tools report, and record its files."""
        from gridlens.analysis.event_index import IndexColumnsMissing, IndexStale, TooManyCases

        try:
            result = query(run, **arguments)
        except IndexStale as exc:
            raise AgentError("INDEX_STALE", "Rebuild the index with run_analysis(include_index=True, rebuild=True), or in the Agent tab.") from exc
        except IndexColumnsMissing as exc:
            raise AgentError("CASE_FIELD_UNAVAILABLE", f"This run's flat result has no {exc} column, so that case metric or qualifier is unavailable.") from exc
        except TooManyCases as exc:
            raise AgentError("QUERY_TOO_LARGE", str(exc)) from exc
        for path in result[-1]:
            self._source(path, run)
        return result

    def _rank_cases(self, run: Path, metric: str, descending: bool, magnitude: int, conditions: list, extra: list[str]) -> tuple[list[dict], int, dict]:
        """Rank a run's indexed cases by metric; return the rows, how many cases qualified, and the counts behind them."""
        from gridlens.analysis.event_index import scan_cases

        scope = self._cases(run, conditions, set(extra))
        rows, total, _ = self._index(
            run, scan_cases, metric=metric, descending=descending, limit=magnitude, events=scope["events"], keys=scope["keys"],
            conditions=scope["index_conditions"], extra=tuple(name for name in extra if name in CASE_INDEX_COLUMNS),
        )
        if scope["keys"] and scope["events"] is None and not scope["index_conditions"] and not total:
            raise AgentError("KEY_NOT_INDEXED", "These facilities are in the analysis cache but not in the drill-down index; rebuild both with run_analysis(include_index=True, rebuild=True).")
        output, failed = [], []
        for position, row in enumerate(rows, 1):
            outage = scope["contingencies"].get(row["event_idx"], BASE_CASE if row["event_idx"] == 0 else None)
            record = case_record(row, scope["facilities"].get(branch_key(row), {}), outage)
            if record["fields"]["converged"] == "false":
                failed.append(row["event_idx"])
            output.append({"rank": position, **record["identity"], "value": reported(row["value"]), **{name: shown(record["fields"][name]) for name in extra}})
        if failed:
            events = ", ".join(str(event) for event in list(dict.fromkeys(failed))[:10])
            self.warnings.append(f"{len(failed)} of these cases are in contingencies that failed or did not converge (event_idx {events}); their flows are not a valid post-contingency state.")
        self.warnings.append("Cases are every recorded row of the drill-down index, including the base case and non-converged contingencies. Voltages and angles are recorded only at the ends of monitored branches.")
        return output, total, {"recorded_cases": self._json(run, "reports/event_index/manifest.json").get("rows")}

    def _group_cases(self, run: Path, group: str, metric: str, statistic: str, conditions: list) -> tuple[list[tuple], dict]:
        """Compute statistic of metric over a run's qualifying indexed cases per group; return the groups and the counts behind them."""
        from gridlens.analysis.event_index import group_cases

        scope = self._cases(run, conditions, {group})
        if group in ("contingency", "type", "status_code", "converged", "outage_area"):
            by = "event"
            outages = {0: BASE_CASE, **scope["contingencies"]}
            labels = {event: [record["fields"]["contingency"]] if group == "contingency" else group_labels(record["fields"], group) for event, record in outages.items()}
        else:
            by = "facility"
            labels = {case_key(*key): [facility_label(key, attributes)] if group == "facility" else group_labels(facility_fields(key, attributes), group) for key, attributes in scope["facilities"].items()}
        accumulators, used, _ = self._index(run, group_cases, metric=metric, statistic=statistic, by=by, labels=labels, events=scope["events"], keys=scope["keys"], conditions=scope["index_conditions"])
        self.warnings.append("Cases are every recorded row of the drill-down index, including the base case and non-converged contingencies. Voltages and angles are recorded only at the ends of monitored branches.")
        groups = [(label, accumulator.result(), accumulator.count) for label, accumulator in accumulators.items() if accumulator.count]
        return groups, {"objects_used": used, "recorded_cases": self._json(run, "reports/event_index/manifest.json").get("rows")}

    @tool
    def rank(self, run_id: str, object: ObjectKind = "branches", order: Order = "descending", metric: ObjectMetric = "max_utilization_pct", magnitude: int = 10, filters: list[ObjectFilter] | None = None, fields: list[ObjectField] | None = None, compare_run_id: str = "", compare_project: str = "", project: str = "") -> dict:
        """Sort objects by one metric and return the first `magnitude` (0 returns all), each with the value it was sorted by; total_matching counts every object that qualified. Facilities and contingencies with no known value, such as a failed contingency's loading, follow the ranked ones with value null.

        object: branches (non-transformer), transformers, or both are facilities at or above 50 kV; their metrics are max_utilization_pct (congestion), base_utilization_pct, mean_utilization_pct, min_utilization_pct, thermal_margin_pct_points, overload_count (cases at or above 100%), contingency_count, rating_mva, and nominal_kv. contingencies are outage cases, converged ones only unless a qualifier names converged or status_code; their metrics are max_loading_pct, overload_count (monitored facilities at or above 100%), monitored_facility_count, iterations, max_p_mismatch, and max_q_mismatch. cases are one facility in one contingency, from the drill-down index; their metrics are loading_percent, mva_from, p_from_mw, q_from_mvar, rate_mva, v_from_pu, v_to_pu, min_voltage_pu, ang_from_deg, ang_to_deg, and angle_difference_deg, and a case also has its facility's and its contingency's fields; its viol field is GridPACK's own flag, which mostly marks the outaged branch itself, not an overload.
        filters keep objects meeting every qualifier, e.g. [{"column": "control_area", "op": "==", "value": "Coast"}, {"column": "nominal_kv", "op": ">=", "value": 345}]; outage_area is where a contingency's outaged element is. control_area holds both ends' areas, the from end's first, so one control_area qualifier per area selects the tie lines between two areas, e.g. [{"column": "control_area", "op": "==", "value": "Far West"}, {"column": "control_area", "op": "==", "value": "West"}], and tie == "true" with one control_area selects an area's ties; the same qualifiers select cases, for flows or angles across an interface. An area name no object has is refused with the names that exist. fields adds attributes to each row. compare_run_id ranks facilities by their change from this run to another (value = other minus this) and allows compare_value and change as qualifiers. For counts, means, or any statistic use rank_groups, never these rows.
        """
        descending = _descending(order)
        family, metric = resolve_metric(object, metric, self.warnings)
        if compare_run_id and family != "facility":
            raise AgentError("COMPARE_FACILITIES_ONLY", "compare_run_id compares facilities; use object='branches', 'transformers', or 'both'.")
        conditions = check_conditions(object, filters, compare=bool(compare_run_id))
        extra = check_fields(object, fields, compare=bool(compare_run_id))
        run = self._run(run_id, project)
        units, definition = metric_units(family, metric)
        header = {
            "object": object, "metric": metric, "order": order, "units": change_units(units) if compare_run_id else units,
            "definition": f"change from this run to the compare run in the {definition}" if compare_run_id else definition, "filters": filters or [],
        }
        if family == "case":
            rows, total, counts = self._rank_cases(run, metric, descending, magnitude, conditions, extra)
            return {**header, **counts, **page_result(rows, total, 0, magnitude)}
        records, counts, value_key = self._population(run, object, family, metric, conditions, fields=tuple(extra), compare_run_id=compare_run_id, compare_project=compare_project, unknown_values="list")
        # Objects with no known value cannot be ranked, but they qualified, so they follow the ranked ones.
        known = sorted((record for record in records if record["values"][value_key] is not None), key=lambda record: (-record["values"][value_key] if descending else record["values"][value_key], _order(record)))
        unknown = sorted((record for record in records if record["values"][value_key] is None), key=_order)
        rows = [
            {"rank": position if position <= len(known) else None, **record["identity"], "value": reported(record["values"][value_key]) if position <= len(known) else None, **{name: shown(record["fields"][name]) for name in extra}}
            for position, record in enumerate(known + unknown, 1)
        ]
        return {**header, **counts, **page_result(rows[:magnitude] if magnitude else rows, len(rows), 0, magnitude)}

    @tool
    def rank_groups(self, run_id: str, group: ObjectGroup = "voltage_class", object: ObjectKind = "branches", order: Order = "descending", metric: ObjectMetric = "max_utilization_pct", statistic: GroupStatistic = "mean", magnitude: int = 10, filters: list[ObjectFilter] | None = None, compare_run_id: str = "", compare_project: str = "", project: str = "") -> dict:
        """Group every qualifying object, compute one statistic of one metric over each group's objects, and return the first `magnitude` groups (0 returns all), each with that statistic and the count of objects it used.

        group for facilities: control_area (a facility joining two areas counts in both), tie (tie lines against facilities inside one area), voltage_class (the voltage groups or categories of the Branch Analysis tab, such as 100-229 kV; transformers group by step direction), nominal_kv (each exact base voltage, such as 138 kV), branch_type, or binding_contingency (the case that set each facility's maximum loading). For contingencies: type, status_code, converged, or outage_area. For cases: contingency, facility, or any facility or contingency group. statistic is mean, median, min, max, std, var (population), iqr, count (every qualifying object, whatever its metric value), or sum (only for additive quantities). metric is a per-object value as in rank, so statistic='mean' of metric='max_utilization_pct' is the mean maximum loading the Branch Analysis tab shows, and of mean_utilization_pct or min_utilization_pct it is the mean mean or mean min. object, metric, filters, and compare_run_id are as in rank; filters remove objects before grouping.
        """
        descending = _descending(order)
        if statistic not in GROUP_STATISTICS:
            raise AgentError("INVALID_STATISTIC", f"Choose a statistic from: {', '.join(GROUP_STATISTICS)}.")
        family, metric = resolve_metric(object, metric, self.warnings)
        check_group(object, group)
        if compare_run_id and family != "facility":
            raise AgentError("COMPARE_FACILITIES_ONLY", "compare_run_id compares facilities; use object='branches', 'transformers', or 'both'.")
        conditions = check_conditions(object, filters, compare=bool(compare_run_id))
        run = self._run(run_id, project)
        if family == "case":
            groups, counts = self._group_cases(run, group, metric, statistic, conditions)
        else:
            records, counts, value_key = self._population(run, object, family, metric, conditions, group=group, compare_run_id=compare_run_id, compare_project=compare_project, unknown_values="count" if statistic == "count" else "exclude")
            members: dict[str, list[float]] = {}
            for record in records:
                for label in group_labels(record["fields"], group):
                    members.setdefault(label, []).append(record["values"][value_key])
            groups = [(label, group_statistic(values, statistic), len(values)) for label, values in members.items()]
            counts["objects_used"] = len(records)
        groups.sort(key=lambda item: (-item[1] if descending else item[1], item[0]))
        rows = [{"rank": position, "group": label, "value": reported(value), "count": count} for position, (label, value, count) in enumerate(groups, 1)]
        units, definition = metric_units(family, metric)
        units = change_units(units) if compare_run_id else units
        return {
            "group": group, "object": object, "metric": metric, "statistic": statistic, "order": order,
            "units": "objects" if statistic == "count" else f"{units}²" if statistic == "var" else units,
            "definitions": {
                "group": GROUP_DEFINITIONS[group], "statistic": STATISTIC_DEFINITIONS[statistic], "count": "the objects each group's value was computed from",
                "metric": f"change from this run to the compare run in the {definition}" if compare_run_id else definition,
            },
            "filters": filters or [], **counts,
            **page_result(rows[:magnitude] if magnitude else rows, len(rows), 0, magnitude),
        }

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
