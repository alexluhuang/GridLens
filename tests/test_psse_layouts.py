from __future__ import annotations

from gridlens.psse import layouts


def test_layouts_put_fields_where_gridpack_reads_them():
    """GridPACK's block parsers read fields by position, pinned here."""
    assert layouts.names(33, "load").index("YQ") == 10
    assert layouts.names(33, "generator").index("PT") == 16
    assert layouts.names(34, "generator").index("NREG") == 28
    assert layouts.names(35, "generator").index("NREG") == 8
    assert layouts.names(35, "generator").index("PT") == 17
    assert layouts.names(35, "generator").index("BASLOD") == 19
    assert layouts.names(33, "branch").index("RATEC") == 8
    assert layouts.names(33, "branch").index("ST") == 13
    assert layouts.names(35, "branch").index("NAME") == 6
    assert layouts.names(35, "branch").index("STAT") == 23


def test_each_version_has_the_psse_field_count_of_each_record():
    counts = {
        version: [len(layouts.names(version, kind)) for kind in layouts.KINDS]
        for version in layouts.VERSIONS
    }

    assert counts == {33: [14, 28, 24], 34: [17, 29, 34], 35: [18, 30, 34]}


def test_the_fields_that_identify_a_record_come_first_in_every_layout():
    for version in layouts.VERSIONS:
        for kind, key in layouts.KEYS.items():
            assert tuple(layouts.names(version, kind)[:len(key)]) == key


def test_the_fields_gridpack_does_not_read_are_marked():
    unread = [f.name for f in layouts.fields(35, "load") if not f.gridpack]

    assert unread == ["OWNER", "SCALE", "INTRPT", "DGENP", "DGENQ", "DGENM",
                      "LOADTYPE"]
    assert all(f.gridpack for f in layouts.fields(35, "generator"))
