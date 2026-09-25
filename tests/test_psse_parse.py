from __future__ import annotations

from pathlib import Path

import pytest

from gridlens.psse import layouts, parse


DATA = Path(__file__).parent / "data"
VERSIONS = (33, 34, 35)


def fields(case: parse.Case, kind: str, index: int = 0) -> dict[str, str]:
    """Return a record's values by field name."""
    record = case.records[kind][index]
    return dict(zip(layouts.names(case.version, kind), record.values))


@pytest.mark.parametrize("version", VERSIONS)
def test_each_version_reads_its_buses_loads_generators_and_branches(version):
    case = parse.read_case(DATA / f"three_bus_v{version}.raw")
    south = case.buses[201]

    assert case.version == version
    assert case.sbase == "100.00"
    assert (south.name, south.ide, south.area, south.owner) == (
        "SOUTH 1", "3", "2", "4")
    counts = [len(case.records[kind]) for kind in layouts.KINDS]
    assert counts == [1, 2, 2]
    assert fields(case, "load")["PL"] == "50.000"
    assert fields(case, "generator", 1)["PT"] == "200.000"
    assert fields(case, "branch", 1)["X"] == "8.00000E-2"
    generator = case.records["generator"][0]
    assert case.record("generator", generator.line) == generator
    assert case.record("load", generator.line) is None


def test_fields_split_at_commas_and_blanks_and_end_at_a_comment():
    line = " 101 102,'A, B',, 3.5 / A comment, not a field\n"

    found = [line[start:end] for start, end in parse.spans(line)]

    assert found == ["101", "102", "'A, B'", "", "3.5"]
    # A comma that ends a line leaves an empty field, as GridPACK reads it.
    short = "1,2,\n"
    assert [short[start:end] for start, end in parse.spans(short)] == [
        "1", "2", ""]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_a_case_is_written_back_byte_for_byte(tmp_path, version, ending):
    # Byte 0x85 is a line break to str.splitlines; it must not split a title.
    text = (DATA / f"three_bus_v{version}.raw").read_text(encoding="latin-1")
    text = text.replace("NOT A REAL NETWORK", "Caf\xe9 \x85 NOT REAL")
    path = tmp_path / "case.raw"
    parse.write_case(path, text.replace("\n", ending))

    case = parse.read_case(path)
    parse.write_case(tmp_path / "copy.raw", "".join(case.lines))

    assert (tmp_path / "copy.raw").read_bytes() == path.read_bytes()
    assert len(case.records["branch"]) == 2


@pytest.mark.parametrize("revision", ["30", "36", ""])
def test_other_raw_versions_are_refused(revision):
    text = (DATA / "three_bus_v33.raw").read_text(encoding="latin-1")
    text = text.replace(" 33, 0, 0,", f" {revision}, 0, 0,", 1)

    with pytest.raises(ValueError, match="versions 33, 34, and 35"):
        parse.parse_case(text)


def test_a_case_that_ends_before_its_branch_data_is_refused():
    text = (DATA / "three_bus_v33.raw").read_text(encoding="latin-1")
    text = text.split("0 / END OF GENERATOR DATA")[0]

    with pytest.raises(ValueError, match="before its generator data ends"):
        parse.parse_case(text)


def test_bus_numbers_ignore_the_metered_end_sign():
    assert parse.bus_number("-201") == 201
    assert parse.bus_number("'NORTH 1'") is None
