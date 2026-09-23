"""Read every record of every section of a PSS/E RAW case file.

The metadata parsers in `raw_parsers` read only the bus, branch, transformer, and area fields the
analysis needs. This module reads the whole case. It splits the file at its `0 / END OF ... DATA, BEGIN
... DATA` markers, joins the multi-line records of transformers and DC lines, and names every field.

Field names follow the PSS/E version 33 layout when the case header says revision 33. For another
revision a record line takes the version 33 names only when it has exactly as many fields as the version
33 line, so no field is ever given a wrong name. A section with `@!` header lines, as versions 34 and 35
can write, takes its names from those lines instead. Any other field is named `field_<n>`, so no value is
ever dropped, only left unnamed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


HEADER_FIELDS = ["IC", "SBASE", "REV", "XFRRAT", "NXFRAT", "BASFRQ"]
_OWNERS = ["O1", "F1", "O2", "F2", "O3", "F3", "O4", "F4"]
_WINDING = ["WINDV{n}", "NOMV{n}", "ANG{n}", "RATA{n}", "RATB{n}", "RATC{n}", "COD{n}", "CONT{n}", "RMA{n}", "RMI{n}", "VMA{n}", "VMI{n}", "NTP{n}", "TAB{n}", "CR{n}", "CX{n}", "CNXA{n}"]
_CONVERTER = ["IBUS", "TYPE", "MODE", "DCSET", "ACSET", "ALOSS", "BLOSS", "MINLOSS", "SMAX", "IMAX", "PWF", "MAXQ", "MINQ", "REMOT", "RMPCT"]
_DC_END = ["IP{s}", "NB{s}", "ANMX{s}", "ANMN{s}", "RC{s}", "XC{s}", "EBAS{s}", "TR{s}", "TAP{s}", "TMX{s}", "TMN{s}", "STP{s}", "IC{s}", "IF{s}", "IT{s}", "ID{s}", "XCAP{s}"]

# Version 33 field names, one list per line of a record.
V33_FIELDS: dict[str, list[list[str]]] = {
    "BUS": [["I", "NAME", "BASKV", "IDE", "AREA", "ZONE", "OWNER", "VM", "VA", "NVHI", "NVLO", "EVHI", "EVLO"]],
    "LOAD": [["I", "ID", "STATUS", "AREA", "ZONE", "PL", "QL", "IP", "IQ", "YP", "YQ", "OWNER", "SCALE", "INTRPT"]],
    "FIXED SHUNT": [["I", "ID", "STATUS", "GL", "BL"]],
    "GENERATOR": [["I", "ID", "PG", "QG", "QT", "QB", "VS", "IREG", "MBASE", "ZR", "ZX", "RT", "XT", "GTAP", "STAT", "RMPCT", "PT", "PB", *_OWNERS, "WMOD", "WPF"]],
    "BRANCH": [["I", "J", "CKT", "R", "X", "B", "RATEA", "RATEB", "RATEC", "GI", "BI", "GJ", "BJ", "ST", "MET", "LEN", *_OWNERS]],
    "AREA": [["I", "ISW", "PDES", "PTOL", "ARNAME"]],
    "TWO-TERMINAL DC": [
        ["NAME", "MDC", "RDC", "SETVL", "VSCHD", "VCMOD", "RCOMP", "DELTI", "METER", "DCVMIN", "CCCITMX", "CCCACC"],
        [name.format(s="R") for name in _DC_END],
        [name.format(s="I") for name in _DC_END],
    ],
    "VOLTAGE SOURCE CONVERTER": [
        ["NAME", "MDC", "RDC", *_OWNERS],
        [f"C1_{name}" for name in _CONVERTER],
        [f"C2_{name}" for name in _CONVERTER],
    ],
    "IMPEDANCE CORRECTION": [["I", *[f"{kind}{n}" for n in range(1, 12) for kind in ("T", "F")]]],
    "MULTI-SECTION LINE": [["I", "J", "ID", "MET", *[f"DUM{n}" for n in range(1, 10)]]],
    "ZONE": [["I", "ZONAME"]],
    "INTER-AREA TRANSFER": [["ARFROM", "ARTO", "TRID", "PTRAN"]],
    "OWNER": [["I", "OWNAME"]],
    "FACTS CONTROL DEVICE": [["NAME", "I", "J", "MODE", "PDES", "QDES", "VSET", "SHMX", "TRMX", "VTMN", "VTMX", "VSMX", "IMX", "LINX", "RMPCT", "OWNER", "SET1", "SET2", "VSREF", "REMOT", "MNAME"]],
    "SWITCHED SHUNT": [["I", "MODSW", "ADJM", "STAT", "VSWHI", "VSWLO", "SWREM", "RMPCT", "RMIDNT", "BINIT", *[f"{kind}{n}" for n in range(1, 9) for kind in ("N", "B")]]],
    "INDUCTION MACHINE": [["I", "ID", "STAT", "SCODE", "DCODE", "AREA", "ZONE", "OWNER", "TCODE", "BCODE", "MBASE", "RATEKV", "PCODE", "PSET", "H", "A", "B", "D", "E", "RA", "XA", "XM", "R1", "X1", "R2", "X2", "X3", "E1", "SE1", "E2", "SE2", "IA1", "IA2", "XAMULT"]],
}
_TRANSFORMER_FIRST = ["I", "J", "K", "CKT", "CW", "CZ", "CM", "MAG1", "MAG2", "NMETR", "NAME", "STAT", *_OWNERS, "VECGRP"]
V33_TWO_WINDING = [_TRANSFORMER_FIRST, ["R1-2", "X1-2", "SBASE1-2"], [name.format(n=1) for name in _WINDING], ["WINDV2", "NOMV2"]]
V33_THREE_WINDING = [
    _TRANSFORMER_FIRST,
    ["R1-2", "X1-2", "SBASE1-2", "R2-3", "X2-3", "SBASE2-3", "R3-1", "X3-1", "SBASE3-1", "VMSTAR", "ANSTAR"],
    *[[name.format(n=n) for name in _WINDING] for n in (1, 2, 3)],
]
# Sections whose records span a fixed number of lines. Transformers span 4 or 5, decided per record.
LINES_PER_RECORD = {"TWO-TERMINAL DC": 3, "VOLTAGE SOURCE CONVERTER": 3}
_MARKER = re.compile(r"^0\s*(/|$)")


@dataclass
class RawSection:
    """One section of a RAW case: its name, the union of its field names, and its records."""

    name: str
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, object]] = field(default_factory=list)


def _split(line: str) -> list[tuple[str, bool]]:
    """Split a RAW data line at commas outside quotes, and mark which fields were quoted.

    A `/` outside quotes starts a comment, as PSS/E allows after a record, and ends the line.
    """
    fields: list[tuple[str, bool]] = []
    current: list[str] = []
    quote, quoted = "", False
    for char in line:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in "'\"":
            quote, quoted = char, True
        elif char == ",":
            fields.append(("".join(current), quoted))
            current, quoted = [], False
        elif char == "/":
            break
        else:
            current.append(char)
    fields.append(("".join(current), quoted))
    return fields


def _value(text: str, quoted: bool) -> object:
    """Return a RAW field: quoted fields stay text, so circuit '01' is not the number 1; others become numbers when they are."""
    stripped = text.strip()
    if quoted:
        return stripped
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        return stripped


def _fields(line: str) -> list[object]:
    """Split one RAW data line into typed fields.

    An empty field between commas is kept as an empty string, because RAW fields are positional.
    """
    parts = _split(line)
    if len(parts) == 1 and not parts[0][0].strip() and not parts[0][1]:
        return []
    return [_value(text, quoted) for text, quoted in parts]


def _named(values: list[object], names: list[str], taken: set[str]) -> dict[str, object]:
    """Pair values with names, naming any value beyond the list, or any repeated name, field_<n>."""
    row = {}
    for index, value in enumerate(values):
        name = names[index] if index < len(names) else f"field_{len(taken) + index + 1}"
        if name in row or name in taken:
            name = f"field_{len(taken) + index + 1}"
        row[name] = value
    return row


def _section_name(marker: str) -> tuple[str | None, str | None]:
    """Return the names of the section a marker line ends and the one it begins, when it names them."""
    upper = marker.upper()
    ended = re.search(r"END OF (.+?) DATA", upper)
    begun = re.search(r"BEGIN (.+?) DATA", upper)
    return (ended.group(1).strip() if ended else None, begun.group(1).strip() if begun else None)


def _record_layout(section: str, first_line: list[object], version: int, headers: list[list[str]]) -> list[list[str]]:
    """Return the field names of each line of the record that starts with first_line."""
    if headers:
        return headers
    if section == "TRANSFORMER":
        three_winding = len(first_line) > 2 and first_line[2] not in (0, "0", "")
        return V33_THREE_WINDING if three_winding else V33_TWO_WINDING
    return V33_FIELDS.get(section, [])


def _records(section: str, lines: list[str], version: int, headers: list[list[str]]) -> RawSection:
    """Group a section's data lines into records and name their fields."""
    result = RawSection(section)
    index = 0
    while index < len(lines):
        first = _fields(lines[index])
        if not first:
            index += 1
            continue
        layout = _record_layout(section, first, version, headers)
        if section == "TRANSFORMER":
            # A third-winding bus K other than 0 makes a five-line record; otherwise it has four lines.
            count = 5 if len(first) > 2 and first[2] not in (0, "0", "") else 4
        else:
            count = LINES_PER_RECORD.get(section, 1)
        row: dict[str, object] = {}
        for offset in range(count):
            if index + offset >= len(lines):
                break
            values = first if offset == 0 else _fields(lines[index + offset])
            names = layout[offset] if offset < len(layout) else []
            if version != 33 and not headers and len(values) != len(names):
                names = []
            row.update(_named(values, names, set(row)))
        index += count
        result.rows.append(row)
    result.columns = list(dict.fromkeys(name for row in result.rows for name in row))
    return result


def read_raw_sections(path: Path) -> tuple[dict[str, object], list[RawSection]]:
    """Read a RAW case into its header fields and a list of sections, in file order.

    The first data section follows the case line and two title lines, and has no BEGIN marker: bus data
    in versions 33 and 34, system-wide data when a file has it. Each section therefore takes its name from
    the marker that ends it. Reading stops at a line holding only Q.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_names = HEADER_FIELDS
    while lines and lines[0].strip().startswith("@!"):
        header_names = [str(_value(text, False)).upper() for text, _ in _split(lines.pop(0).strip()[2:])]
    header_values = _fields(lines[0]) if lines else []
    header = _named(header_values, header_names, set())
    header["TITLE1"] = lines[1].strip() if len(lines) > 1 else ""
    header["TITLE2"] = lines[2].strip() if len(lines) > 2 else ""
    try:
        version = int(header.get("REV") or 0)
    except (TypeError, ValueError):
        version = 0
    sections: list[RawSection] = []
    current, data, headers = "BUS", [], []
    for line in lines[3:]:
        stripped = line.strip()
        if stripped.upper() == "Q":
            break
        if stripped.startswith("@!"):
            headers.append([str(_value(text, False)).upper() for text, _ in _split(stripped[2:])])
            continue
        if _MARKER.match(stripped):
            ended, begun = _section_name(stripped)
            sections.append(_records(ended or current or f"SECTION {len(sections) + 1}", data, version, headers))
            # A marker that begins nothing is followed only by sections that name themselves as they end.
            current, data, headers = begun or "", [], []
            continue
        data.append(line)
    if data:
        sections.append(_records(current or f"SECTION {len(sections) + 1}", data, version, headers))
    return header, sections


def find_section(sections: list[RawSection], name: str) -> RawSection:
    """Return the section called name, ignoring case and a trailing ' DATA', or raise KeyError."""
    wanted = re.sub(r"\s+DATA$", "", name.strip().upper())
    for section in sections:
        if section.name == wanted:
            return section
    raise KeyError(name)


__all__ = ["RawSection", "find_section", "read_raw_sections"]
