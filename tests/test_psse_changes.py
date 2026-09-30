"""Change requests that name records by bus and ID resolve to the patcher's edits."""
from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from gridlens.psse import changes, layouts, parse, patch


DATA = Path(__file__).parent / "data"
VERSIONS = (33, 34, 35)


def read(version: int) -> parse.Case:
    return parse.read_case(DATA / f"three_bus_v{version}.raw")


def after(case: parse.Case, edits: list[patch.Edit], kind: str, index: int = 0) -> dict[str, str]:
    """Return a record's values by field name once the edits are made."""
    edited = parse.parse_case(patch.apply(case, edits))
    return dict(zip(layouts.names(case.version, kind), edited.records[kind][index].values))


@pytest.mark.parametrize("version", VERSIONS)
def test_a_branch_is_found_from_either_end_and_the_status_field_takes_any_spelling(version):
    """STATUS, STAT, and ST all name the in-service field, whatever this version calls it."""
    case = read(version)
    for spelling in ("status", "STAT", "st"):
        edits = changes.resolve(case, [{"action": "set", "kind": "branch", "bus": 102, "to_bus": 101, "id": "1", "values": {spelling: 0}}])
        assert [(edit.kind, edit.line, edit.values) for edit in edits] == [("branch", case.records["branch"][0].line, {changes.status_field(version, "branch"): "0"})]
    assert changes.status_field(version, "load") == ("STATUS" if version == 33 else "STAT")


@pytest.mark.parametrize("version", VERSIONS)
def test_scaling_by_a_mw_change_keeps_the_power_factor_and_writes_the_decimals_it_found(version):
    case = read(version)
    edits = changes.resolve(case, [{"action": "scale", "kind": "load", "area": 1, "change_mw": 5}])
    values = after(case, edits, "load")
    assert (values["PL"], values["QL"]) == ("55.000", "11.000")
    before, later = changes.totals(case), changes.totals(case, edits)
    assert (later.load_mw - before.load_mw, later.load_mvar - before.load_mvar) == pytest.approx((5.0, 1.0))
    assert later.load_mw_by_area == {"1": 55.0}


def test_scale_selects_only_in_service_records_of_the_named_area():
    case = read(33)
    # The only load is in area 1; area 2 has none, and an out-of-service load is not scaled.
    with pytest.raises(changes.ChangeError, match="No in-service load matches area 2"):
        changes.resolve(case, [{"action": "scale", "kind": "load", "area": 2, "factor": 1.1}])
    with pytest.raises(changes.ChangeError, match="No in-service load"):
        changes.resolve(case, [
            {"action": "set", "kind": "load", "bus": 102, "values": {"STATUS": 0}},
            {"action": "scale", "kind": "load", "factor": 1.1},
        ])
    # A generator has no area of its own, so it is scaled by its bus's area.
    edits = changes.resolve(case, [{"action": "scale", "kind": "generator", "area": 2, "factor": 2}])
    assert after(case, edits, "generator", 1)["PG"] == "20.000" and after(case, edits, "generator", 0)["PG"] == "40.000"


def test_requests_apply_in_order_and_merge_into_one_edit_per_record():
    case = read(33)
    edits = changes.resolve(case, [
        {"action": "set", "kind": "load", "bus": 102, "id": "1", "values": {"PL": 60}},
        {"action": "scale", "kind": "load", "bus": 102, "factor": 1.5},
    ])
    assert len(edits) == 1 and edits[0].values == {"PL": "90.000", "QL": "15.000"}
    removed = changes.resolve(case, [{"action": "remove", "kind": "generator", "bus": 201}])
    assert removed[0].removed and removed[0].line == case.records["generator"][1].line
    with pytest.raises(changes.ChangeError, match="Change 2: .* is removed by an earlier change"):
        changes.resolve(case, [{"action": "remove", "kind": "load", "bus": 102}, {"action": "set", "kind": "load", "bus": 102, "values": {"PL": 1}}])


def test_added_records_take_unused_ids_and_psse_defaults():
    case = read(33)
    edits = changes.resolve(case, [
        {"action": "add", "kind": "load", "bus": 102, "values": {"PL": 3}},
        {"action": "add", "kind": "load", "bus": 102, "values": {"PL": 4}},
        {"action": "add", "kind": "branch", "bus": 101, "to_bus": 201, "values": {"X": 0.1, "RATEA": 150}},
    ])
    assert [edit.values["ID"] for edit in edits[:2]] == ["2", "3"]
    assert edits[0].values["AREA"] == "1" and edits[0].values["QL"] == "0.0"
    assert edits[2].values["CKT"] == "1" and edits[2].values["X"] == "0.1" and patch.check(case, edits) == []
    assert changes.totals(case, edits).load_mw == pytest.approx(57.0)


def test_ambiguous_or_missing_records_are_refused_with_what_the_case_has():
    case = read(33)
    two = parse.parse_case(patch.apply(case, changes.resolve(case, [{"action": "add", "kind": "load", "bus": 102, "id": "2", "values": {"PL": 1}}])))
    with pytest.raises(changes.ChangeError, match="2 loads at bus 102, with IDs 1, 2. Name one with id"):
        changes.resolve(two, [{"action": "set", "kind": "load", "bus": 102, "values": {"PL": 1}}])
    with pytest.raises(changes.ChangeError, match="No load at bus 102 has ID 9; the case has IDs 1 there"):
        changes.resolve(case, [{"action": "set", "kind": "load", "bus": 102, "id": "9", "values": {"PL": 1}}])
    with pytest.raises(changes.ChangeError, match="no branch between buses 101 and 201"):
        changes.resolve(case, [{"action": "remove", "kind": "branch", "bus": 101, "to_bus": 201}])
    with pytest.raises(changes.ChangeError, match="Bus 999 is not in the case"):
        changes.resolve(case, [{"action": "remove", "kind": "load", "bus": 999}])
    with pytest.raises(changes.ChangeError, match="has no field RATE9"):
        changes.resolve(case, [{"action": "set", "kind": "branch", "bus": 101, "to_bus": 102, "values": {"RATE9": 1}}])


@pytest.mark.parametrize("request_", [
    {"action": "scale", "kind": "load", "factor": 105},
    {"action": "scale", "kind": "load", "factor": 1.1, "change_mw": 5},
    {"action": "scale", "kind": "load"},
    {"action": "scale", "kind": "load", "change_mw": -60},
    {"action": "scale", "kind": "branch", "factor": 1.1},
    {"action": "set", "kind": "load", "bus": 102, "values": {}},
    {"action": "set", "kind": "load", "bus": 102, "values": {"PL": True}},
    {"action": "move", "kind": "load", "bus": 102},
    {"action": "set", "kind": "shunt", "bus": 102},
])
def test_incomplete_or_implausible_requests_are_refused(request_):
    with pytest.raises(changes.ChangeError, match="^Change 1: "):
        changes.resolve(read(33), [request_])


def test_an_unbalanced_change_names_the_swing_generator_that_supplies_it():
    case = read(33)
    edits = changes.resolve(case, [{"action": "scale", "kind": "load", "change_mw": 20}])
    notes = changes.balance_notes(case, changes.totals(case), changes.totals(case, edits))
    assert len(notes) == 1 and "rises 20.0 MW more than generation" in notes[0] and "bus 201 SOUTH 1 (PG 10.000 MW, PT 200.000 MW)" in notes[0]
    balanced = changes.resolve(case, [{"action": "scale", "kind": "load", "change_mw": 20}, {"action": "scale", "kind": "generator", "bus": 101, "change_mw": 20}])
    assert changes.balance_notes(case, changes.totals(case), changes.totals(case, balanced)) == []


def test_only_the_edited_fields_change_in_the_written_case():
    case = read(34)
    edits = changes.resolve(case, [{"action": "set", "kind": "generator", "bus": 101, "id": "1", "values": {"PG": 45.5, "STAT": "0"}}])
    diff = [line for line in difflib.unified_diff(case.lines, patch.apply(case, edits).splitlines(True), n=0) if line[:1] in "+-" and line[:3] not in ("---", "+++")]
    assert len(diff) == 2
    old, new = diff[0][1:], diff[1][1:]
    assert new.replace("      45.5", "    40.000").replace(",0,  100.0,", ",1,  100.0,") == old


def test_an_area_can_be_named_as_the_case_names_it():
    case = read(35)
    by_name = changes.resolve(case, [{"action": "scale", "kind": "load", "area": "north", "factor": 1.2}])
    assert by_name == changes.resolve(case, [{"action": "scale", "kind": "load", "area": 1, "factor": 1.2}])
    # PSS/E cuts area names to 12 characters, so a longer name matches the start the case kept.
    assert changes.area_number(case, "Northern region") == 1
    with pytest.raises(changes.ChangeError, match="The case's areas are: 1 NORTH, 2 SOUTH"):
        changes.resolve(case, [{"action": "scale", "kind": "load", "area": "Coast", "factor": 1.2}])


def test_each_scale_request_says_what_it_selected():
    case = read(33)
    selections: list[str] = []
    changes.resolve(case, [
        {"action": "set", "kind": "load", "bus": 102, "values": {"PL": 60}},
        {"action": "scale", "kind": "load", "area": "north", "change_mw": 6},
        {"action": "scale", "kind": "generator", "factor": 1.5},
    ], selections)
    assert selections == [
        "Change 2 scales PL and QL of 1 in-service load in area 1 NORTH by 1.1.",
        "Change 3 scales PG of 2 in-service generators in the whole case by 1.5.",
    ]
