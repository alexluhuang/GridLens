"""Read the buses, loads, generators, and branches of a PSS/E RAW case.

Reading follows GridPACK's ``PTI33_parser.hpp``, ``PTI34_parser.hpp``, and
``PTI35_parser.hpp`` and the helpers in ``block_parsers/base_block_parser``:
a line that starts with ``@!`` or ``//`` is a comment, a record whose first
field is 0 ends a section, the case record is followed by two title lines,
versions 34 and 35 then give a section of system-wide data, and the bus,
load, fixed shunt, generator, and branch sections follow in that order.

A case keeps every line of its file, so a patch can change a few of them
and write the rest back as they were.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
import io
from pathlib import Path
import re
import sys

from gridlens.psse import layouts


# The sections from the case record to the end of the branch data.
_SECTIONS = {
    33: ("bus", "load", "fixed shunt", "generator", "branch"),
    34: ("system-wide", "bus", "load", "fixed shunt", "generator", "branch"),
    35: ("system-wide", "bus", "load", "fixed shunt", "generator", "branch"),
}
# A quoted string, a run of other characters, a comma, or a slash.
_TOKEN = re.compile(r"""'[^']*'?|"[^"]*"?|[^\s,'"/]+|[,/]""")
_SECTION_END = re.compile(r"0(\s|,|/|$)")
_BUS_NUMBER = re.compile(r"[+-]?\d+")


@dataclass(frozen=True)
class Bus:
    """The fields of a bus that its loads, generators, and branches use.

    ide is the bus type: 1 load, 2 generator, 3 swing, 4 isolated.
    """

    number: int
    name: str
    base_kv: str
    ide: str
    area: str
    zone: str
    owner: str


@dataclass(frozen=True)
class Record:
    """A load, generator, or branch: the index of its line and its values.

    values may hold fewer values than the layout has fields, when the file
    leaves trailing fields out.
    """

    line: int
    values: tuple[str, ...]


@dataclass
class Case:
    """A RAW case: its lines, its buses, and the records GridLens can edit.

    ends gives the index of the line that ends each section.
    """

    version: int
    sbase: str
    lines: list[str]
    buses: dict[int, Bus]
    records: dict[str, list[Record]]
    ends: dict[str, int]

    def record(self, kind: str, line: int) -> Record | None:
        """Return the record of a kind on a line, or None."""
        records = self.records[kind]
        position = bisect.bisect_left(records, line, key=_line_of)
        if position < len(records) and records[position].line == line:
            return records[position]
        return None


def read_case(path: str | Path) -> Case:
    """Read a RAW case of version 33, 34, or 35 from a file.

    The file is read as Latin-1, which maps every byte to one character, so
    writing the text back with write_case restores it byte for byte.
    """
    with Path(path).open(encoding="latin-1", newline="") as handle:
        return parse_case(handle.read())


def write_case(path: str | Path, text: str) -> None:
    """Write the text of a case, keeping its bytes and line endings."""
    Path(path).write_text(text, encoding="latin-1", newline="")


def parse_case(text: str) -> Case:
    """Find the buses and the load, generator, and branch records of a case.

    Raises ValueError when the case is not version 33, 34, or 35, or when it
    ends before its branch data does.
    """
    lines = io.StringIO(text, newline="").readlines()
    index = 0
    while index < len(lines) and _is_comment(lines[index]):
        index += 1
    if index == len(lines):
        raise ValueError("The file has no case identification record.")
    header = _values(lines[index])
    version = _version(header)
    sbase = header[1] if len(header) > 1 else "100.0"
    index += 3  # The case record and its two title lines.
    records = {}
    ends = {}
    for section in _SECTIONS[version]:
        end = _section_end(lines, index, section)
        if section == "bus" or section in layouts.KINDS:
            records[section] = _records(lines, index, end)
        ends[section] = end
        index = end + 1
    buses = {}
    for record in records.pop("bus"):
        bus = _bus(record.values)
        if bus is not None:
            buses[bus.number] = bus
    return Case(version, sbase, lines, buses, records, ends)


def spans(line: str) -> list[tuple[int, int]]:
    """Return where each field of a data line starts and ends.

    Fields are separated by commas or blanks, and a quoted field may hold
    either. Two commas with nothing between them leave an empty field, and a
    slash outside quotes starts a comment, as GridPACK's splitPSSELine and
    cleanComment read a line.
    """
    found = []
    expecting = True  # Nothing has been read since the start or a comma.
    after_comma = None
    for match in _TOKEN.finditer(line):
        token = match.group()
        if token == "/":
            break
        if token == ",":
            if expecting:
                found.append((match.start(), match.start()))
            expecting, after_comma = True, match.end()
        else:
            found.append(match.span())
            expecting, after_comma = False, None
    if after_comma is not None:
        found.append((after_comma, after_comma))
    return found


def bus_number(text: str) -> int | None:
    """Return the bus number a field holds, or None when it holds none.

    A minus sign, which PSS/E reads as marking the metered end of a branch,
    does not change the bus.
    """
    return abs(int(text)) if _BUS_NUMBER.fullmatch(text) else None


def _records(lines: Sequence[str], start: int, end: int) -> list[Record]:
    """Return the records of the lines from start to end, skipping comments.

    A line with no fields, such as one holding only a comment after a
    slash, is skipped too, as GridPACK finds no bus on it.
    """
    records = []
    for index in range(start, end):
        if not _is_comment(lines[index]):
            values = _values(lines[index])
            if values:
                records.append(Record(index, values))
    return records


def _values(line: str) -> tuple[str, ...]:
    """Return the values of a data line, without quotes or blanks.

    Values are interned, since a large case repeats the same few thousand
    values, such as 0.00 and 1.0000, millions of times.
    """
    return tuple(
        sys.intern(_unquote(line[start:end])) for start, end in spans(line))


def _unquote(text: str) -> str:
    """Remove the quotes around a field, then its surrounding blanks."""
    if text[:1] in ("'", '"'):
        closed = len(text) > 1 and text[-1] == text[0]
        text = text[1:-1] if closed else text[1:]
    return text.strip()


def _version(header: Sequence[str]) -> int:
    """Return the RAW version of a case record, which is its third field."""
    text = header[2] if len(header) > 2 else ""
    if not text.isdigit() or int(text) not in layouts.VERSIONS:
        raise ValueError(
            "GridLens can edit PSS/E RAW versions 33, 34, and 35, and this "
            f"case gives version {text or 'none'}.")
    return int(text)


def _section_end(lines: Sequence[str], start: int, section: str) -> int:
    """Return the index of the line that ends the section at start.

    A record whose first field is 0 ends a section, as GridPACK's test_end
    reads it; a line holding only Q ends the case.
    """
    for index in range(start, len(lines)):
        text = lines[index].strip()
        if text.upper() == "Q":
            break
        if _SECTION_END.match(text):
            return index
    raise ValueError(f"The case ends before its {section} data ends.")


def _is_comment(line: str) -> bool:
    """Return whether a line is blank or a comment, like check_comment."""
    text = line.strip()
    return not text or text.startswith(("@!", "//"))


def _bus(values: Sequence[str]) -> Bus | None:
    """Return a bus from its record, or None when it has no bus number.

    A bus record starts with I, NAME, BASKV, IDE, AREA, ZONE, and OWNER in
    every version GridLens reads. A field the record leaves out takes the
    value PSS/E assumes for it.
    """
    number = bus_number(values[0])
    if number is None:
        return None
    fields = [*values[:7], *[""] * (7 - len(values))]
    ide, area, zone, owner = (text or "1" for text in fields[3:7])
    return Bus(number, fields[1], fields[2], ide, area, zone, owner)


def _line_of(record: Record) -> int:
    """Return the line index of a record, to search records by line."""
    return record.line
