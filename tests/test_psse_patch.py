from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from gridlens.psse import layouts, parse, patch


DATA = Path(__file__).parent / "data"
VERSIONS = (33, 34, 35)


def read(version: int) -> parse.Case:
    return parse.read_case(DATA / f"three_bus_v{version}.raw")


def fields(case: parse.Case, kind: str, index: int = 0) -> dict[str, str]:
    """Return a record's values by field name."""
    record = case.records[kind][index]
    return dict(zip(layouts.names(case.version, kind), record.values))


def changed_lines(case: parse.Case, text: str) -> list[str]:
    """Return the removed (-) and added (+) lines of a patch."""
    new = text.splitlines(keepends=True)
    diff = difflib.unified_diff(case.lines, new, n=0)
    return [
        line for line in diff
        if line[:1] in "+-" and line[:3] not in ("---", "+++")
    ]


def new_record(case: parse.Case, kind: str, buses: list[int],
               **values: str) -> patch.Edit:
    """Return an edit that adds a record at buses, with some values set."""
    taken = [record.values for record in case.records[kind]]
    names = layouts.names(case.version, kind)
    defaults = patch.new_values(case, kind, buses, taken)
    return patch.Edit(kind, None, {**dict(zip(names, defaults)), **values})


@pytest.mark.parametrize("version", VERSIONS)
def test_a_case_without_edits_is_unchanged(version):
    case = read(version)

    assert patch.apply(case, []) == "".join(case.lines)


@pytest.mark.parametrize("version", VERSIONS)
def test_changing_a_field_rewrites_only_that_field(version):
    case = read(version)
    generator = case.records["generator"][0]
    edit = patch.Edit("generator", generator.line, {"PG": "123.4"})

    text = patch.apply(case, [edit])

    old, new = changed_lines(case, text)
    assert old[1:].replace("    40.000", "     123.4") == new[1:]
    assert fields(parse.parse_case(text), "generator")["PG"] == "123.4"


def test_a_changed_line_keeps_its_line_ending_and_comment():
    case = read(33)
    tie = case.records["branch"][1]
    crlf = parse.parse_case("".join(case.lines).replace("\n", "\r\n"))

    text = patch.apply(crlf, [patch.Edit("branch", tie.line, {"ST": "0"})])

    line = text.splitlines(keepends=True)[tie.line]
    assert line.endswith("1,1.0000 / TIE LINE\r\n")
    assert fields(parse.parse_case(text), "branch", 1)["ST"] == "0"


@pytest.mark.parametrize("version", VERSIONS)
def test_removing_a_record_deletes_only_its_line(version):
    case = read(version)
    load = case.records["load"][0]

    text = patch.apply(case, [patch.Edit("load", load.line, removed=True)])

    assert changed_lines(case, text) == ["-" + case.lines[load.line]]
    assert parse.parse_case(text).records["load"] == []


@pytest.mark.parametrize("version", VERSIONS)
def test_added_records_go_just_before_the_end_of_their_section(version):
    case = read(version)
    edits = [
        new_record(case, "load", [201], PL="75.0"),
        new_record(case, "generator", [101], PG="25.0"),
        new_record(case, "branch", [101, 201], X="0.1"),
    ]

    text = patch.apply(case, edits)

    lines = text.splitlines()
    for offset, kind in enumerate(layouts.KINDS):
        # Each earlier section's new record moves this section's end down.
        end = case.ends[kind] + offset + 1
        assert lines[end].startswith("0 / END OF")
        assert lines[end - 1].split(",")[0] == edits[offset].values["I"]
    patched = parse.parse_case(text)
    counts = [len(patched.records[kind]) for kind in layouts.KINDS]
    assert counts == [2, 3, 3]
    assert fields(patched, "branch", 2)["X"] == "0.1"


def test_a_new_record_takes_its_defaults_from_its_bus_and_the_case():
    case = read(35)

    names = layouts.names(35, "load")
    load = dict(zip(names, patch.new_values(case, "load", [201], [])))
    generator = new_record(case, "generator", [101]).values
    branch = new_record(case, "branch", [201, 101]).values

    assert (load["AREA"], load["ZONE"], load["OWNER"]) == ("2", "3", "4")
    assert load["ID"] == "1"
    assert generator["ID"] == "2"  # Generator 101 ID 1 already exists.
    assert (generator["MBASE"], generator["O1"]) == ("100.00", "1")
    assert (generator["QT"], generator["PB"]) == ("9999.0", "-9999.0")
    assert branch["CKT"] == "1"  # No branch joins 201 and 101 yet.
    assert branch["O1"] == "4"
    assert branch["X"] == ""  # A planner must give a new branch its X.


def test_a_field_the_record_leaves_out_is_added_in_its_position():
    """The version 33 fixture's generators end at F1, field 20 of 28."""
    case = read(33)
    generator = case.records["generator"][0]
    edit = patch.Edit("generator", generator.line, {"WMOD": "1"})

    text = patch.apply(case, [edit])

    values = fields(parse.parse_case(text), "generator")
    assert len(values) == 27  # The line ends at WMOD; WPF keeps its default.
    assert (values["F1"], values["O2"], values["F4"]) == ("1.0000", "0", "1.0")
    assert values["WMOD"] == "1"


@pytest.mark.parametrize("version", (34, 35))
def test_text_is_quoted_and_padded_as_psse_writes_it(version):
    case = read(version)
    branch = case.records["branch"][0]
    edit = patch.Edit("branch", branch.line, {"CKT": "2", "NAME": "NEW NAME"})

    text = patch.apply(case, [edit])

    line = text.splitlines()[branch.line]
    assert "'2 '" in line
    assert "'NEW NAME" + " " * 32 + "'" in line


def test_blank_separated_records_are_read_and_patched():
    case = read(33)
    load = case.records["load"][0]
    lines = list(case.lines)
    lines[load.line] = " 102 '1' 1 1 1 50.0 10.0 0.0 0.0 0.0 0.0 1 1 0\n"
    blank = parse.parse_case("".join(lines))

    edit = patch.Edit("load", load.line, {"QL": "12.5"})
    text = patch.apply(blank, [edit])

    expected = " 102 '1' 1 1 1 50.0 12.5 0.0 0.0 0.0 0.0 1 1 0"
    assert text.splitlines()[load.line] == expected


def test_invalid_values_are_refused_with_every_problem_listed():
    case = read(34)
    load = case.records["load"][0]
    branch = case.records["branch"][0]
    edits = [
        patch.Edit("load", load.line, {"STAT": "1.5", "PL": "lots", "ID": ""}),
        patch.Edit("branch", branch.line,
                   {"X": "0.0", "NAME": "A/B, C", "CKT": "ABC"}),
    ]

    with pytest.raises(ValueError) as refused:
        patch.apply(case, edits)

    load_name, branch_name = "Load 102 ID 1", "Branch 101 to 102 circuit 1"
    assert str(refused.value).splitlines() == [
        f"{load_name}: STAT must be a whole number.",
        f"{load_name}: PL must be a number, such as 12.5 or 1.2E-3.",
        f"{load_name}: ID must not be empty.",
        f"{branch_name}: X must not be zero.",
        f"{branch_name}: NAME may not hold quotes, commas, or slashes, "
        "which GridPACK cannot read.",
        f"{branch_name}: CKT may hold at most 2 characters.",
    ]


def test_records_must_name_buses_in_the_case_and_keep_ids_unique():
    case = read(33)
    edits = [
        patch.Edit("load", case.records["load"][0].line, {"I": "999"}),
        new_record(case, "generator", [101], ID="1"),
        new_record(case, "branch", [102, 101], X="0.2", CKT="1"),
    ]

    problems = patch.check(case, edits)

    assert problems == [
        "Load 999 ID 1: bus 999 is not in the case.",
        "Generator 101 ID 1: another generator has the same buses and ID.",
        "Branch 102 to 101 circuit 1: another branch has the same buses "
        "and circuit.",
    ]
    with pytest.raises(ValueError, match="Bus 999 is not in the case"):
        patch.new_values(case, "load", [999], [])


def test_moving_a_record_away_frees_its_id_for_a_new_one():
    case = read(33)
    generator = case.records["generator"][0]
    edits = [
        patch.Edit("generator", generator.line, {"I": "102"}),
        new_record(case, "generator", [101], ID="1"),
    ]

    assert patch.check(case, edits) == []


def test_a_generator_added_at_a_load_bus_is_flagged():
    case = read(35)
    at_load_bus = new_record(case, "generator", [102])
    out_of_service = new_record(case, "generator", [102], ID="2", STAT="0")
    at_generator_bus = new_record(case, "generator", [101])

    edits = [at_load_bus, out_of_service, at_generator_bus]
    notes = patch.warnings(case, edits)

    assert len(notes) == 1
    assert notes[0].startswith("Generator 102 ID 1: bus 102 is a load bus")


def test_describe_and_summary_report_each_edit():
    case = read(33)
    generator = case.records["generator"][0]
    load = case.records["load"][0]
    edits = [
        patch.Edit("generator", generator.line, {"PG": "50.0"}),
        patch.Edit("load", load.line, removed=True),
        new_record(case, "branch", [101, 201], X="0.1"),
    ]

    described = patch.describe(case, edits)

    assert described[0] == {
        "kind": "generator",
        "action": "change",
        "record": "Generator 101 ID 1",
        "line": generator.line + 1,
        "fields": {"PG": {"from": "40.000", "to": "50.0"}},
    }
    assert described[1] == {
        "kind": "load",
        "action": "remove",
        "record": "Load 102 ID 1",
        "line": load.line + 1,
    }
    assert described[2]["action"] == "add"
    assert described[2]["record"] == "Branch 101 to 201 circuit 1"
    assert patch.summary(edits) == "1 added, 1 changed, 1 removed"
