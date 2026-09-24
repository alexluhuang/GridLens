"""The objects rank and rank_groups sort and group, and the words a model uses to ask for them.

Three families of object share one vocabulary. Facilities are the branches and transformers of a run's
analysis cache, at or above the 50 kV cutoff. Contingencies are its outage cases, from the compact
contingency summary and the convergence file. Cases are one facility in one contingency: the rows of the
drill-down index. A case carries the attributes of its facility and of its contingency, so a qualifier
such as control_area or outage_area means the same thing wherever it applies.

The Literal types are the unions that go into the tools' schemas. `FAMILIES` decides which metric,
field, and group each family accepts, and every check here names the valid choices when it refuses one.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, TypedDict, get_args

from gridlens.agent.file_tools import FILTER_OPERATORS, FilterOperator, cell_passes
from gridlens.agent.policy import AgentError
from gridlens.analysis.event_index import CASE_METRICS, case_key
from gridlens.analysis.loading import branch_key
from gridlens.analysis.utilization import NONTRANSFORMER_BRANCH


ObjectKind = Literal["branches", "transformers", "both", "contingencies", "cases"]
ObjectMetric = Literal[
    "max_utilization_pct", "base_utilization_pct", "mean_utilization_pct", "min_utilization_pct",
    "thermal_margin_pct_points", "overload_count", "contingency_count", "rating_mva", "nominal_kv",
    "max_loading_pct", "monitored_facility_count", "iterations", "max_p_mismatch", "max_q_mismatch",
    "loading_percent", "mva_from", "p_from_mw", "q_from_mvar", "rate_mva", "v_from_pu", "v_to_pu", "min_voltage_pu",
    "ang_from_deg", "ang_to_deg", "angle_difference_deg",
]
ObjectGroup = Literal[
    "control_area", "voltage_class", "nominal_kv", "branch_type", "binding_contingency",
    "contingency", "facility", "type", "status_code", "converged", "outage_area",
]
ObjectField = Literal[
    "control_area", "voltage_class", "nominal_kv", "branch_type", "binding_contingency", "bus", "bus_name",
    "from_bus", "to_bus", "line_id", "section", "max_utilization_pct", "base_utilization_pct",
    "mean_utilization_pct", "min_utilization_pct", "thermal_margin_pct_points", "overload_count",
    "contingency_count", "rating_mva", "compare_value", "change", "rating_changed",
    "event_idx", "contingency", "type", "converged", "status_code", "outage_area", "worst_facility",
    "max_loading_pct", "monitored_facility_count", "iterations", "max_p_mismatch", "max_q_mismatch",
    "viol", "loading_percent", "mva_from", "p_from_mw", "q_from_mvar", "rate_mva", "v_from_pu", "v_to_pu",
    "min_voltage_pu", "ang_from_deg", "ang_to_deg", "angle_difference_deg",
]
Order = Literal["descending", "ascending"]


class ObjectFilter(TypedDict):
    """One qualifier. An object is kept only when every qualifier holds; control_area, outage_area, bus, and bus_name match either end."""

    column: ObjectField
    op: FilterOperator
    value: Any


# The facility types each object selects, as the loading tools name them.
OBJECT_KINDS = {"branches": "line", "transformers": "transformer", "both": "all"}
FAMILY_OF = {"branches": "facility", "transformers": "facility", "both": "facility", "contingencies": "contingency", "cases": "case"}
# Each facility metric's units, its definition, and whether it is a loading, which is unknown without a positive rating.
FACILITY_METRICS = {
    "max_utilization_pct": ("%", "highest loading over every recorded case, including the base case and non-converged cases", True),
    "base_utilization_pct": ("%", "loading in the base case", True),
    "mean_utilization_pct": ("%", "mean loading over every recorded case", True),
    "min_utilization_pct": ("%", "lowest loading over every recorded case", True),
    "thermal_margin_pct_points": ("percentage points", "100 minus maximum loading; not transfer, generation, or load-serving capacity", True),
    "overload_count": ("cases", "recorded cases, including the base case, with loading of at least 100%", True),
    "contingency_count": ("cases", "recorded loading cases, including the base case", False),
    "rating_mva": ("MVA", "the rating that loading percentages are computed against", False),
    "nominal_kv": ("kV", "the higher of the two end base voltages", False),
}
CONTINGENCY_METRICS = {
    "max_loading_pct": ("%", "highest absolute loading of any monitored facility in the contingency"),
    "overload_count": ("facilities", "monitored facilities loaded at or above 100% in the contingency"),
    "monitored_facility_count": ("facilities", "monitored facilities recorded for the contingency"),
    "iterations": ("iterations", "power-flow iterations the solution took"),
    "max_p_mismatch": ("as reported", "largest real-power mismatch left at the solution, in GridPACK's units"),
    "max_q_mismatch": ("as reported", "largest reactive-power mismatch left at the solution, in GridPACK's units"),
}
FACILITY_ATTRIBUTES = ("control_area", "voltage_class", "nominal_kv", "branch_type", "bus", "bus_name", "from_bus", "to_bus", "line_id", "section")
CONTINGENCY_ATTRIBUTES = ("event_idx", "contingency", "type", "converged", "status_code", "outage_area")
COMPARE_FIELDS = ("compare_value", "change", "rating_changed")
GROUP_DEFINITIONS = {
    "control_area": "the control area of each end; an object joining two areas counts in both",
    "voltage_class": "the GridLens voltage class of the higher end; transformers group as step-up, step-down, or same-voltage",
    "nominal_kv": "the higher end's base voltage",
    "branch_type": "the RAW branch type",
    "binding_contingency": "the case in which the facility reached its maximum loading",
    "contingency": "the contingency, or the base case",
    "facility": "the facility, by its full branch key",
    "type": "the contingency type the convergence file records, such as branch or generator",
    "status_code": "the solution status the convergence file records, such as OK or ISLANDED",
    "converged": "whether the contingency's power flow converged with status OK",
    "outage_area": "the control areas of the outaged element's buses; an outage joining two areas counts in both",
}
FAMILIES = {
    "facility": {
        "metrics": tuple(FACILITY_METRICS), "default": "max_utilization_pct",
        "fields": (*FACILITY_ATTRIBUTES, "binding_contingency", *FACILITY_METRICS),
        "groups": ("control_area", "voltage_class", "nominal_kv", "branch_type", "binding_contingency"),
    },
    "contingency": {
        "metrics": tuple(CONTINGENCY_METRICS), "default": "max_loading_pct",
        "fields": (*CONTINGENCY_ATTRIBUTES, "worst_facility", *CONTINGENCY_METRICS),
        "groups": ("type", "status_code", "converged", "outage_area"),
    },
    "case": {
        "metrics": tuple(CASE_METRICS), "default": "loading_percent",
        "fields": (*FACILITY_ATTRIBUTES, *CONTINGENCY_ATTRIBUTES, "viol", *CASE_METRICS),
        "groups": ("contingency", "facility", "control_area", "voltage_class", "nominal_kv", "branch_type", "type", "status_code", "converged", "outage_area"),
    },
}
# Case qualifiers the index filters numerically; the others select events or facilities first.
CASE_INDEX_COLUMNS = (*CASE_METRICS, "viol")
NUMERIC_OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "in")
# GridPACK names an outage after its element: BR_<from>_<to>_<circuit> for a branch, GN_<bus>_<id> for a generator.
OUTAGE_BUSES = re.compile(r"^(?:BR|BRANCH|LINE|XF|TR)_(\d+)_(\d+)(?:_|$)|^(?:GN|GEN|G|LOAD|LD)_(\d+)(?:_|$)", re.IGNORECASE)
assert set(get_args(ObjectMetric)) == {name for family in FAMILIES.values() for name in family["metrics"]}
assert set(get_args(ObjectGroup)) == {name for family in FAMILIES.values() for name in family["groups"]}
assert set(get_args(ObjectField)) == {name for family in FAMILIES.values() for name in family["fields"]} | set(COMPARE_FIELDS)


def family_of(kind: str) -> str:
    """Return the family of an object kind, refusing an unknown kind."""
    if kind not in FAMILY_OF:
        raise AgentError("INVALID_OBJECT", f"Choose object from: {', '.join(FAMILY_OF)}.")
    return FAMILY_OF[kind]


def resolve_metric(kind: str, metric: str, warnings: list[str]) -> tuple[str, str]:
    """Return the family and the metric to use, taking a family's own maximum-loading metric for max_utilization_pct."""
    family = family_of(kind)
    choices = FAMILIES[family]["metrics"]
    if metric in choices:
        return family, metric
    if metric == "max_utilization_pct":
        # The default names the facility metric; each family has its own measure of maximum loading.
        substitute = FAMILIES[family]["default"]
        warnings.append(f"max_utilization_pct is a facility metric; object='{kind}' was ranked by {substitute} instead.")
        return family, substitute
    raise AgentError("INVALID_METRIC", f"For object='{kind}' choose a metric from: {', '.join(choices)}.")


def metric_units(family: str, metric: str) -> tuple[str, str]:
    """Return a metric's units and definition."""
    if family == "facility":
        return FACILITY_METRICS[metric][:2]
    if family == "contingency":
        return CONTINGENCY_METRICS[metric]
    return CASE_METRICS[metric][:2]


def check_conditions(kind: str, filters: list | None, *, compare: bool = False) -> list[tuple[str, str, object]]:
    """Check qualifiers against the object's fields and return them as (column, op, value) triples."""
    family = family_of(kind)
    fields = (*FAMILIES[family]["fields"], *(COMPARE_FIELDS if compare else ()))
    example = "{'column': 'control_area', 'op': '==', 'value': 'Coast'}"
    if filters is None:
        return []
    if not isinstance(filters, list):
        raise AgentError("INVALID_FILTER", f"Give filters as a list of qualifiers such as {example}.")
    checked = []
    for item in filters:
        if not isinstance(item, dict) or item.get("column") not in fields or item.get("op") not in FILTER_OPERATORS or "value" not in item:
            raise AgentError("INVALID_FILTER", f"Use qualifiers such as {example}, with op one of {', '.join(FILTER_OPERATORS)}, and for object='{kind}' a column from: {', '.join(fields)}.")
        if item["op"] == "in" and not isinstance(item["value"], list):
            raise AgentError("INVALID_FILTER", "The 'in' operator needs a list value.")
        if family == "case" and item["column"] in CASE_INDEX_COLUMNS and item["op"] not in NUMERIC_OPERATORS:
            raise AgentError("INVALID_FILTER", f"{item['column']} is a number; qualify it with one of {', '.join(NUMERIC_OPERATORS)}.")
        checked.append((item["column"], item["op"], item["value"]))
    return checked


def check_fields(kind: str, fields: list | None, *, compare: bool = False) -> list[str]:
    """Check the extra fields rank returns beside each object's value, keeping their order."""
    names = (*FAMILIES[family_of(kind)]["fields"], *(COMPARE_FIELDS if compare else ()))
    if fields is None:
        return []
    if not isinstance(fields, list) or any(name not in names for name in fields):
        raise AgentError("INVALID_FIELD", f"For object='{kind}' choose fields from: {', '.join(names)}.")
    return list(dict.fromkeys(fields))


def check_group(kind: str, group: str) -> None:
    """Refuse a group the object's family cannot form."""
    choices = FAMILIES[family_of(kind)]["groups"]
    if group not in choices:
        raise AgentError("INVALID_GROUP", f"For object='{kind}' choose a group from: {', '.join(choices)}.")


def facility_record(row: dict) -> dict:
    """Describe one _loading row as rank sees it: its identity, the fields qualifiers test, and its metric values.

    A facility without a positive rating has an unknown loading, so its loading metrics are None rather
    than the 0% GridPACK reports.
    """
    from_bus, to_bus, line_id, section = branch_key(row)
    nominal = max(_number(row.get("from_base_kv")) or 0, _number(row.get("to_base_kv")) or 0) or None
    values = {name: _number(row.get(name)) for name in FACILITY_METRICS}
    values["nominal_kv"] = nominal
    if not row["utilization_known"]:
        values.update({name: None for name, (_, _, loading) in FACILITY_METRICS.items() if loading})
    fields = {
        "control_area": list(row["control_areas"]), "voltage_class": row["voltage_group"], "nominal_kv": nominal,
        "branch_type": row.get("raw_branch_type") or NONTRANSFORMER_BRANCH,
        "binding_contingency": row.get("max_contingency_label") or "unknown",
        "bus": [from_bus, to_bus], "bus_name": [row.get("from_bus_name", ""), row.get("to_bus_name", "")],
        "from_bus": from_bus, "to_bus": to_bus, "line_id": line_id, "section": section, **values,
    }
    identity = {"object": row["line_label"], "from_bus": from_bus, "to_bus": to_bus, "line_id": line_id, "section": section}
    return {"identity": identity, "fields": fields, "values": values, "rating_basis": row["rating_basis"]}


def contingency_record(event: int, summary: dict, convergence: dict, bus_areas: dict, facilities: dict) -> dict:
    """Describe one contingency from its compact-summary row and its convergence row, either of which may be empty."""
    name = " ".join(str(summary.get("contingency") or convergence.get("contingency") or "").split())
    values = {name_: _number(summary.get(name_)) for name_ in ("max_loading_pct", "monitored_facility_count")}
    # The summary's violation_count also counts GridPACK's viol flag, which marks the outaged branch itself.
    values["overload_count"] = _number(summary.get("thermal_overload_count"))
    values.update({name_: _number(convergence.get(name_)) for name_ in ("iterations", "max_p_mismatch", "max_q_mismatch")})
    if convergence:
        status = str(convergence.get("status_code") or "OK").strip().upper() or "OK"
        converged = "true" if str(convergence.get("converged", "")).strip().lower() in ("true", "1") and status == "OK" else "false"
    else:
        status, converged = "unknown", "unknown"
    worst = ""
    if summary.get("worst_facility_key"):
        try:
            key = branch_key(dict(zip(("from_bus", "to_bus", "line_id", "section"), json.loads(summary["worst_facility_key"]))))
            worst = facility_label(key, facilities.get(key, {}))
        except (TypeError, ValueError):
            worst = str(summary["worst_facility_key"])
    fields = {
        "event_idx": event, "contingency": name, "type": str(convergence.get("type") or "unknown").strip() or "unknown",
        "converged": converged, "status_code": status, "outage_area": outage_areas(name, bus_areas),
        "worst_facility": worst, **values,
    }
    return {"identity": {"event_idx": event, "contingency": name}, "fields": fields, "values": values}


# The base case is a recorded case but not a contingency: it outages nothing.
BASE_CASE = {"fields": {"event_idx": 0, "contingency": "base_case", "type": "base", "converged": "unknown", "status_code": "unknown", "outage_area": ["none"]}}


def facility_label(key: tuple, attributes: dict) -> str:
    """Return a facility's label, naming its section when it has one so sections stay apart."""
    label = attributes.get("object") or case_key(*key)
    return f"{label} section {key[3]}" if key[3] else label


def facility_fields(key: tuple, attributes: dict) -> dict:
    """Return the qualifier fields of one facility from its `facility_attributes` entry and full key."""
    return {
        "control_area": list(attributes.get("control_area") or ["unknown"]), "voltage_class": attributes.get("voltage_class", "unknown"),
        "nominal_kv": attributes.get("nominal_kv"), "branch_type": attributes.get("branch_type", "unknown"),
        "bus": [key[0], key[1]], "bus_name": list(attributes.get("bus_name") or ["", ""]),
        "from_bus": key[0], "to_bus": key[1], "line_id": key[2], "section": key[3],
    }


def case_value(row: dict, name: str) -> float | None:
    """Return one case metric of an index row as the index scans compute it."""
    if name == "loading_percent":
        value = row.get("loading_percent")
        return abs(value) if value is not None else None
    if name == "min_voltage_pu":
        known = [value for value in (row.get("v_from_pu"), row.get("v_to_pu")) if value is not None]
        return min(known) if known else None
    if name == "angle_difference_deg":
        first, second = row.get("ang_from_deg"), row.get("ang_to_deg")
        return abs(first - second) if first is not None and second is not None else None
    return row.get(name)


def case_record(row: dict, attributes: dict, contingency: dict | None) -> dict:
    """Describe one index row: its identity, and the fields of its facility, its contingency, and itself."""
    key = branch_key(row)
    outage = (contingency or {}).get("fields", {})
    fields = {
        **facility_fields(key, attributes),
        **{name: outage.get(name, ["unknown"] if name == "outage_area" else "unknown") for name in ("type", "converged", "status_code", "outage_area")},
        "event_idx": row["event_idx"], "contingency": row["contingency"], "viol": row.get("viol"),
        **{name: case_value(row, name) for name in CASE_METRICS},
    }
    identity = {"event_idx": row["event_idx"], "contingency": row["contingency"], "object": facility_label(key, attributes), "from_bus": key[0], "to_bus": key[1], "line_id": key[2], "section": key[3]}
    return {"identity": identity, "fields": fields}


def outage_areas(name: str, bus_areas: dict) -> list[str]:
    """Return the control areas of the buses a contingency's name says it outages, or ["unknown"]."""
    match = OUTAGE_BUSES.match(name.strip())
    if not match:
        return ["unknown"]
    buses = [int(number) for number in match.groups() if number]
    areas = list(dict.fromkeys(bus_areas[bus] for bus in buses if bus in bus_areas))
    return areas or ["unknown"]


def qualifies(record: dict, conditions: list[tuple[str, str, object]]) -> bool:
    """Return whether an object meets every qualifier. An unknown value meets none; a two-ended field matches either end."""
    for column, op, value in conditions:
        cell = record["fields"][column]
        if cell is None:
            return False
        if isinstance(cell, list):
            ends = [cell_passes(item, op, value) for item in cell]
            if not (all(ends) if op == "!=" else any(ends)):
                return False
        elif not cell_passes(cell, op, value):
            return False
    return True


def group_labels(fields: dict, group: str) -> list[str]:
    """Return the groups an object belongs to: two for a facility or outage joining two areas, otherwise one."""
    value = fields.get(group)
    if isinstance(value, list):
        return [str(item) for item in value] or ["unknown"]
    if group == "nominal_kv":
        return [f"{value:g} kV" if value else "unknown"]
    return [str(value) if value not in (None, "") else "unknown"]


def change_units(units: str) -> str:
    """Return the units of a difference between two runs' values of a metric in units."""
    return "percentage points" if units == "%" else units


def reported(value: float) -> float | int:
    """Return a value as a whole number when it is one, else rounded to six decimals like the other tools."""
    return int(value) if float(value).is_integer() else round(value, 6)


def shown(value: object) -> object:
    """Return a field value as a result row shows it: numbers as reported gives them, others unchanged."""
    if isinstance(value, float):
        return reported(value)
    return value


def _number(value: object) -> float | None:
    """Return value as a finite float, or None."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None
