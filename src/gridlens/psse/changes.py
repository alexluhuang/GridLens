"""Turn change requests that name records by their buses and IDs into patch edits.

The Sensitivity Analysis tab edits a case one table cell at a time. A caller without a table, such as
the planning agent, names records instead: a load or a generator by its bus and ID, a branch by its two
buses and circuit, or every in-service load or generator of an area, a zone, or a bus, to scale.
`resolve` finds each record and returns the `patch.Edit` list that `patch.apply` makes, so a case edited
this way is written exactly as one edited in the tab.

A request is a dict with an action:

- ``set``: change fields of one record, such as ``{"action": "set", "kind": "branch", "bus": 101,
  "to_bus": 102, "id": "1", "values": {"STAT": 0}}``;
- ``remove``: remove one record;
- ``add``: add a record at a bus, or between two buses for a branch, with the values it names and
  PSS/E's defaults for the rest;
- ``scale``: multiply fields of every in-service load or generator selected by area, zone, or bus,
  either by ``factor`` or so that the first field's total changes by ``change_mw``.

Requests apply in order, so a later request sees what an earlier one changed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import re
from typing import Any, Literal, NotRequired, TypedDict

from gridlens.psse import layouts, parse, patch


ACTIONS = ("set", "remove", "add", "scale")
# The fields scale multiplies when a request names none: a load's constant power, a generator's output.
SCALED_FIELDS = {"load": ("PL", "QL"), "generator": ("PG",)}
# The largest factor scale accepts, so a slip such as 105 for 5% is refused rather than applied.
MAX_FACTOR = 10.0
_STATUS_NAMES = ("STATUS", "STAT", "ST")
_DECIMAL = re.compile(r"[+-]?\d*\.(\d+)")


class ChangeError(ValueError):
    """A change request that cannot be made, with a message for the person who asked."""


class CaseChange(TypedDict):
    """One change to a case: set fields of, remove, or add a load, generator, or branch, or scale loads or generators.

    A load or generator is named by bus and id; a branch by bus, to_bus, and id, its circuit. values holds
    field values by RAW field name, such as PL, PG, or STAT. scale selects in-service records by area
    (its number or its name in the case's area data), zone, or bus (none selects every one), and multiplies
    fields (PL and QL for loads, PG for generators, by default) by factor, or so that the first field's
    total changes by change_mw.
    """

    action: Literal["set", "remove", "add", "scale"]
    kind: Literal["load", "generator", "branch"]
    bus: NotRequired[int]
    to_bus: NotRequired[int]
    id: NotRequired[str]
    values: NotRequired[dict[str, Any]]
    factor: NotRequired[float]
    change_mw: NotRequired[float]
    fields: NotRequired[list[str]]
    area: NotRequired[int | str]
    zone: NotRequired[int]


@dataclass(frozen=True)
class Totals:
    """In-service load and generation of a case, in MW and Mvar, overall and by area."""

    load_mw: float
    load_mvar: float
    generation_mw: float
    load_mw_by_area: dict[str, float]
    generation_mw_by_area: dict[str, float]


def status_field(version: int, kind: str) -> str:
    """Return the name of a record's in-service field, which differs by kind and RAW version."""
    names = layouts.names(version, kind)
    return next(name for name in _STATUS_NAMES if name in names)


def field_name(case: parse.Case, kind: str, name: object) -> str:
    """Return the layout's name for a field a request names, accepting any spelling of the status field."""
    text = str(name).strip().upper()
    if text in _STATUS_NAMES:
        return status_field(case.version, kind)
    if text not in layouts.names(case.version, kind):
        raise ChangeError(f"A {kind} record of version {case.version} has no field {name}. Its fields are {', '.join(layouts.names(case.version, kind))}.")
    return text


def resolve(case: parse.Case, requests: Sequence[Mapping[str, Any]], selections: list[str] | None = None) -> list[patch.Edit]:
    """Return the edits that make the requested changes, merging several changes to one record.

    selections, when given, receives a sentence for each scale request saying what it selected, such as
    "Change 1 scales PL and QL of 451 in-service loads in area 7 Coast by 1.05.". Raises ChangeError,
    naming the request, when a record cannot be found or a request is incomplete. The edits' values are
    checked by patch.check when they are applied.
    """
    if not requests:
        raise ChangeError("Give at least one change.")
    pending: dict[tuple[str, int], dict[str, str]] = {}
    removed: set[tuple[str, int]] = set()
    added: list[patch.Edit] = []
    for number, request in enumerate(requests, 1):
        if not isinstance(request, Mapping):
            raise ChangeError(f"Change {number} is not an object with an action and a kind.")
        try:
            described = _apply_request(case, request, pending, removed, added)
            if described and selections is not None:
                selections.append(f"Change {number} {described}")
        except ChangeError as exc:
            raise ChangeError(f"Change {number}: {exc}") from None
    edits = [patch.Edit(kind, line, dict(values)) for (kind, line), values in pending.items() if values and (kind, line) not in removed]
    edits += [patch.Edit(kind, line, removed=True) for kind, line in sorted(removed)]
    return edits + added


def totals(case: parse.Case, edits: Sequence[patch.Edit] = ()) -> Totals:
    """Return the in-service load and generation of a case once edits are made.

    A load counts toward its own AREA; a generator, which has no area field, toward its bus's area.
    """
    changed = {(edit.kind, edit.line): edit for edit in edits if edit.line is not None}
    load_mw = load_mvar = generation_mw = 0.0
    load_by_area: dict[str, float] = {}
    generation_by_area: dict[str, float] = {}
    for kind in ("load", "generator"):
        records = [(record.line, record) for record in case.records[kind]]
        values = [
            None if changed.get((kind, line)) and changed[(kind, line)].removed
            else _values(case, kind, line, changed.get((kind, line)))
            for line, _ in records
        ]
        values += [dict(zip(layouts.names(case.version, kind), patch.values_after(case, edit))) for edit in edits if edit.kind == kind and edit.line is None]
        status = status_field(case.version, kind)
        for record in values:
            if record is None or record.get(status, "1") != "1":
                continue
            if kind == "load":
                mw = _number(record.get("PL"))
                area = record.get("AREA", "")
                load_mw += mw
                load_mvar += _number(record.get("QL"))
                load_by_area[area] = load_by_area.get(area, 0.0) + mw
            else:
                mw = _number(record.get("PG"))
                bus = case.buses.get(parse.bus_number(record.get("I", "")))
                area = bus.area if bus else ""
                generation_mw += mw
                generation_by_area[area] = generation_by_area.get(area, 0.0) + mw
    return Totals(load_mw, load_mvar, generation_mw, load_by_area, generation_by_area)


def balance_notes(case: parse.Case, before: Totals, after: Totals) -> list[str]:
    """Return a sentence saying who supplies a change in load that generation does not match.

    GridPACK leaves the difference to the swing generator, and a contingency whose swing generator
    exceeds its limits fails, so a large imbalance can leave a run with few converged contingencies.
    """
    net = (after.load_mw - before.load_mw) - (after.generation_mw - before.generation_mw)
    if abs(net) < 0.0005:
        return []
    swings = []
    names = layouts.names(case.version, "generator")
    for record in case.records["generator"]:
        values = dict(zip(names, patch.values_after(case, patch.Edit("generator", record.line))))
        bus = case.buses.get(parse.bus_number(values["I"]))
        if bus is not None and bus.ide == "3" and values.get("STAT") == "1":
            swings.append(f"bus {bus.number} {bus.name}".rstrip() + f" (PG {values['PG']} MW, PT {values['PT']} MW)")
    direction = "rises" if net > 0 else "falls"
    who = "the swing generator at " + "; ".join(swings) if swings else "the swing bus"
    return [
        f"Load {direction} {abs(net):,.1f} MW more than generation does. GridPACK's power flow leaves the difference to "
        f"{who}, and a contingency in which that generator exceeds its limits fails to solve. Change generation "
        "too if the study should rebalance it."
    ]


def _apply_request(case: parse.Case, request: Mapping[str, Any], pending: dict, removed: set, added: list) -> str:
    """Add one request's changes to the edits being gathered; return what a scale request selected, or ""."""
    action = request.get("action")
    kind = request.get("kind")
    if action not in ACTIONS:
        raise ChangeError(f"action must be one of {', '.join(ACTIONS)}.")
    if kind not in layouts.KINDS:
        raise ChangeError(f"kind must be one of {', '.join(layouts.KINDS)}.")
    if action == "scale":
        return _scale(case, kind, request, pending, removed)
    if action == "add":
        added.append(_add(case, kind, request, added))
        return ""
    record = find(case, kind, request.get("bus"), request.get("id"), request.get("to_bus"))
    key = (kind, record.line)
    if key in removed:
        raise ChangeError(f"{patch.label(kind, record.values)} is removed by an earlier change.")
    if action == "remove":
        removed.add(key)
        return ""
    values = request.get("values")
    if not isinstance(values, Mapping) or not values:
        raise ChangeError("set needs values, the fields to change and their new values, such as {\"STAT\": 0}.")
    for name, value in values.items():
        pending.setdefault(key, {})[field_name(case, kind, name)] = _text(value, name)
    return ""


def find(case: parse.Case, kind: str, bus: object, record_id: object = None, to_bus: object = None) -> parse.Record:
    """Return the record of a kind at a bus, or between two buses for a branch, with an ID or circuit.

    With no ID the bus must have exactly one record of the kind, or the two buses exactly one circuit.
    """
    buses = [_bus(bus, "bus")] + ([_bus(to_bus, "to_bus")] if kind == "branch" else [])
    for number in buses:
        if number not in case.buses:
            raise ChangeError(f"Bus {number} is not in the case.")
    place = patch.key(kind, [*map(str, buses), ""])[:-1]
    matches = [record for record in case.records[kind] if patch.key(kind, record.values)[:-1] == place]
    where = f"between buses {buses[0]} and {buses[1]}" if kind == "branch" else f"at bus {buses[0]}"
    noun = "circuit" if kind == "branch" else "ID"
    found = sorted({patch.key(kind, record.values)[-1] for record in matches})
    if record_id not in (None, ""):
        wanted = str(record_id).strip()
        matches = [record for record in matches if patch.key(kind, record.values)[-1] == wanted]
        if not matches:
            listed = f"; the case has {noun}s {', '.join(found)} there" if found else f"; the case has no {kind} there"
            raise ChangeError(f"No {kind} {where} has {noun} {wanted}{listed}.")
    elif len(matches) > 1:
        raise ChangeError(f"The case has {len(matches)} {kind}s {where}, with {noun}s {', '.join(found)}. Name one with id.")
    if not matches:
        raise ChangeError(f"The case has no {kind} {where}.")
    if len(matches) > 1:
        raise ChangeError(f"The case has {len(matches)} {kind} records {where} with the same {noun}; edit them in the Sensitivity Analysis tab.")
    return matches[0]


def _add(case: parse.Case, kind: str, request: Mapping[str, Any], added: Sequence[patch.Edit]) -> patch.Edit:
    """Return the edit that adds a record, taking an unused ID unless the request names one."""
    buses = [_bus(request.get("bus"), "bus")] + ([_bus(request.get("to_bus"), "to_bus")] if kind == "branch" else [])
    taken = [record.values for record in case.records[kind]] + [patch.values_after(case, edit) for edit in added if edit.kind == kind]
    try:
        values = patch.new_values(case, kind, buses, taken)
    except ValueError as exc:
        raise ChangeError(str(exc)) from None
    names = layouts.names(case.version, kind)
    record = dict(zip(names, values))
    if request.get("id") not in (None, ""):
        record[layouts.KEYS[kind][-1]] = str(request["id"]).strip()
    for name, value in (request.get("values") or {}).items():
        field = field_name(case, kind, name)
        if field in layouts.BUS_FIELDS[kind]:
            raise ChangeError(f"Give the buses of a new {kind} as bus" + (" and to_bus." if kind == "branch" else "."))
        record[field] = _text(value, name)
    return patch.Edit(kind, None, record)


def _scale(case: parse.Case, kind: str, request: Mapping[str, Any], pending: dict, removed: set) -> str:
    """Multiply fields of the in-service records a scale request selects, and say what it selected."""
    if kind == "branch":
        raise ChangeError("scale applies to loads and generators; set a branch's fields instead.")
    if isinstance(request.get("area"), str) and not request["area"].strip().isdigit():
        request = {**request, "area": area_number(case, request["area"])}
    fields = [field_name(case, kind, name) for name in request.get("fields") or SCALED_FIELDS[kind]]
    status = status_field(case.version, kind)
    selected = []
    for record in case.records[kind]:
        key = (kind, record.line)
        if key in removed:
            continue
        values = _values(case, kind, record.line, patch.Edit(kind, record.line, pending.get(key, {})))
        if values.get(status) == "1" and _selected(case, kind, values, request):
            selected.append((key, values))
    if not selected:
        raise ChangeError(f"No in-service {kind} matches {_scope(request)}.")
    factor = _factor(request, selected, fields[0], kind)
    for key, values in selected:
        for field in fields:
            pending.setdefault(key, {})[field] = _scaled(values.get(field, "0"), factor)
    noun = kind if len(selected) == 1 else f"{kind}s"
    return f"scales {' and '.join(fields)} of {len(selected):,} in-service {noun} in {_scope(request, case)} by {factor:.6g}."


def area_number(case: parse.Case, name: str) -> int:
    """Return the number of the area a name gives, ignoring case and PSS/E's 12-character cut of names."""
    try:
        areas = parse.read_areas(case)
    except ValueError:
        areas = {}
    wanted = name.strip().casefold()
    exact = [number for number, text in areas.items() if text.strip().casefold() == wanted]
    close = [number for number, text in areas.items() if text.strip() and (wanted.startswith(text.strip().casefold()) or text.strip().casefold().startswith(wanted))]
    matches = exact or close
    if len(matches) == 1:
        return matches[0]
    listed = ", ".join(f"{number} {text.strip()}" for number, text in sorted(areas.items())) or "none"
    raise ChangeError(f"No single area is named {name!r}. The case's areas are: {listed}.")


def _factor(request: Mapping[str, Any], selected: Sequence, field: str, kind: str) -> float:
    """Return a scale request's factor, given directly or from the MW change it asks for."""
    has_factor = request.get("factor") not in (None, "")
    has_change = request.get("change_mw") not in (None, "")
    if has_factor == has_change:
        raise ChangeError("scale needs either factor, such as 1.05 for 5% more, or change_mw, the MW to add (negative to remove), but not both.")
    if has_factor:
        factor = _float(request["factor"], "factor")
    else:
        total = sum(_number(values.get(field)) for _, values in selected)
        if abs(total) < 1e-9:
            raise ChangeError(f"The selected {kind}s have no {field} to scale, so a change in MW cannot be spread over them.")
        factor = (total + _float(request["change_mw"], "change_mw")) / total
    if not 0 < factor <= MAX_FACTOR:
        raise ChangeError(f"The factor would be {factor:.4g}; it must be above 0 and at most {MAX_FACTOR:g}. A factor of 1.05 adds 5%.")
    return factor


def _selected(case: parse.Case, kind: str, values: Mapping[str, str], request: Mapping[str, Any]) -> bool:
    """Return whether a record lies in the area, zone, and bus a scale request names.

    A load has its own AREA and ZONE fields; a generator takes its bus's.
    """
    bus = case.buses.get(parse.bus_number(values.get("I", "")))
    area = values.get("AREA") if kind == "load" else (bus.area if bus else "")
    zone = values.get("ZONE") if kind == "load" else (bus.zone if bus else "")
    wanted = {"area": area, "zone": zone, "bus": str(bus.number) if bus else ""}
    for name, actual in wanted.items():
        if request.get(name) not in (None, "", 0) and str(_bus(request[name], name)) != str(actual).strip():
            return False
    return True


def _scope(request: Mapping[str, Any], case: parse.Case | None = None) -> str:
    """Describe what a scale request selects, such as "area 7 Coast and zone 3", naming an area as the case does."""
    try:
        names = parse.read_areas(case) if case is not None else {}
    except ValueError:
        names = {}
    parts = []
    for name in ("area", "zone", "bus"):
        if request.get(name) in (None, "", 0):
            continue
        label = f"{name} {request[name]}"
        if name == "area" and str(request[name]).strip().isdigit() and names.get(int(str(request[name]).strip())):
            label += f" {names[int(str(request[name]).strip())].strip()}"
        parts.append(label)
    return " and ".join(parts) or "the whole case"


def _values(case: parse.Case, kind: str, line: int, edit: patch.Edit | None) -> dict[str, str]:
    """Return a record's field values by name once an edit to it is made."""
    return dict(zip(layouts.names(case.version, kind), patch.values_after(case, edit or patch.Edit(kind, line))))


def _scaled(text: str, factor: float) -> str:
    """Return a RAW number multiplied by factor, written with at least the decimals it had."""
    value = _number(text) * factor
    stripped = str(text).strip()
    if "e" in stripped.lower():
        return f"{value:.5E}"
    match = _DECIMAL.fullmatch(stripped)
    decimals = max(len(match.group(1)), 3) if match else 3
    written = f"{value:.{decimals}f}"
    return written.lstrip("-") if float(written) == 0 else written


def _text(value: object, name: object) -> str:
    """Return a requested field value as RAW text, refusing values that are neither numbers nor text."""
    if isinstance(value, bool) or value is None or isinstance(value, (list, dict)):
        raise ChangeError(f"{name} needs a number or text, not {value!r}.")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ChangeError(f"{name} must be a finite number.")
        return repr(value)
    return str(value).strip()


def _bus(value: object, name: str) -> int:
    """Return a bus, area, or zone number from a request, refusing anything that is not a whole number."""
    if isinstance(value, bool):
        raise ChangeError(f"{name} must be a whole number.")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ChangeError(f"{name} must be a whole number.") from None
    return abs(number)


def _float(value: object, name: str) -> float:
    """Return a number from a request, refusing text and infinities."""
    if isinstance(value, bool):
        raise ChangeError(f"{name} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ChangeError(f"{name} must be a number.") from None
    if not math.isfinite(number):
        raise ChangeError(f"{name} must be a finite number.")
    return number


def _number(text: object) -> float:
    """Return a RAW numeric field as a float, reading a blank or malformed field as 0."""
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0
