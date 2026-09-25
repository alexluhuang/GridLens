"""Patch the loads, generators, and branches of a PSS/E RAW case.

A patch changes only what it must: the text of each edited field, the line
of each removed record, and one new line for each added record, placed just
before the end of its section. Every other character of the case, including
the spacing between fields, comments, line endings, and the sections
GridLens does not read, is written back unchanged.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
import re

from gridlens.psse import layouts, parse


_INT = re.compile(r"[+-]?\d+")
_FLOAT = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
# GridPACK splits a record at every comma, even inside quotes, and cuts it
# at the first slash that is not inside its first quoted field.
_UNREADABLE = frozenset("'\",/")


@dataclass
class Edit:
    """A change to one load, generator, or branch.

    line is the index of the record to change or remove, or None to add a
    record. values maps field names to new values: the changed fields of a
    record, or every field of a new one.
    """

    kind: str
    line: int | None = None
    values: dict[str, str] = field(default_factory=dict)
    removed: bool = False


def defaults(case: parse.Case, kind: str, bus: int | None) -> dict[str, str]:
    """Return the value PSS/E assumes for each field of a record at a bus.

    A load takes its area, zone, and owner from its bus, a generator or a
    branch takes its first owner from its bus I, and a generator's machine
    base is the case's system base.
    """
    values = {f.name: f.default for f in layouts.fields(case.version, kind)}
    home = case.buses.get(bus)
    if home is not None and kind == "load":
        values.update(AREA=home.area, ZONE=home.zone, OWNER=home.owner)
    elif home is not None:
        values["O1"] = home.owner
    if kind == "generator":
        values["MBASE"] = case.sbase
    return values


def new_values(case: parse.Case, kind: str, buses: Sequence[int],
               taken: Sequence[Sequence[str]]) -> list[str]:
    """Return the field values of a new record, with an unused ID.

    buses holds the record's bus I, and bus J for a branch. taken holds the
    values of the records of that kind the new one must not repeat, such as
    every record in an editing table. Raises ValueError when a bus is not in
    the case.
    """
    for bus in buses:
        if bus not in case.buses:
            raise ValueError(f"Bus {bus} is not in the case.")
    values = defaults(case, kind, buses[0])
    for name, bus in zip(layouts.BUS_FIELDS[kind], buses):
        values[name] = str(bus)
    names = layouts.names(case.version, kind)
    place = key(kind, [values[name] for name in names])[:-1]
    used = set()
    for row in taken:
        row_key = key(kind, row)
        if row_key[:-1] == place:
            used.add(row_key[-1])
    number = 1
    while str(number) in used:
        number += 1
    values[layouts.KEYS[kind][-1]] = str(number)
    return [values[name] for name in names]


def key(kind: str, values: Sequence[str]) -> tuple[str, ...]:
    """Return what identifies a record: its buses and its ID or circuit.

    These are the first fields of every layout. A branch is the same branch
    whichever end the file lists first.
    """
    size = len(layouts.KEYS[kind])
    fields = [*values[:size], *[""] * (size - len(values))]
    buses = [_bus_text(text) for text in fields[:-1]]
    if kind == "branch":
        buses.sort()
    return (*buses, fields[-1])


def label(kind: str, values: Sequence[str]) -> str:
    """Name a record for a person, such as "Generator 101 ID 1"."""
    fields = [*values[:3], "", "", ""]
    if kind == "branch":
        return f"Branch {fields[0]} to {fields[1]} circuit {fields[2]}"
    return f"{kind.capitalize()} {fields[0]} ID {fields[1]}"


def check(case: parse.Case, edits: Sequence[Edit]) -> list[str]:
    """Return a sentence for each problem that stops the edits being made."""
    counts = Counter(edit.line for edit in edits if edit.line is not None)
    problems = [
        f"Line {line + 1} has more than one edit."
        for line, count in counts.items()
        if count > 1
    ]
    for edit in edits:
        problems += _check_edit(case, edit)
    if not problems:
        for kind in layouts.KINDS:
            problems += _check_keys(case, kind, edits)
    return problems


def check_value(field: layouts.Field, value: str) -> str:
    """Return why a value cannot be written to a field, or ""."""
    if field.kind == "text":
        if not (value.isascii() and value.isprintable()):
            return f"{field.name} may hold only plain ASCII characters."
        if _UNREADABLE & set(value):
            return (f"{field.name} may not hold quotes, commas, or slashes, "
                    "which GridPACK cannot read.")
        if len(value) > field.width:
            return f"{field.name} may hold at most {field.width} characters."
        return ""
    if field.kind == "int" and not _INT.fullmatch(value):
        return f"{field.name} must be a whole number."
    if field.kind == "float" and not _FLOAT.fullmatch(value):
        return f"{field.name} must be a number, such as 12.5 or 1.2E-3."
    return ""


def warnings(case: parse.Case, edits: Sequence[Edit]) -> list[str]:
    """Return a sentence for each edit GridPACK may not model as intended.

    GridPACK makes only a generator bus (type 2) hold its voltage, so a
    generator in service at a load bus stays at its PG and QG.
    """
    notes = []
    names = layouts.names(case.version, "generator")
    for edit in edits:
        if edit.kind != "generator" or edit.removed:
            continue
        after = values_after(case, edit)
        values = dict(zip(names, after))
        bus = case.buses.get(parse.bus_number(values["I"]))
        if bus is not None and bus.ide == "1" and values["STAT"] == "1":
            notes.append(
                f"{label('generator', after)}: bus {bus.number} is a load "
                "bus (type 1), so GridPACK will hold the generator at its PG "
                "and QG instead of letting it regulate voltage.")
    return notes


def values_after(case: parse.Case, edit: Edit) -> list[str]:
    """Return every field value of a record once an edit is made.

    Fields the file leaves out take the values PSS/E assumes for them.
    """
    names = layouts.names(case.version, edit.kind)
    if edit.line is None:
        return [edit.values.get(name, "") for name in names]
    record = case.record(edit.kind, edit.line)
    assumed = defaults(case, edit.kind, parse.bus_number(record.values[0]))
    missing = names[len(record.values):]
    values = [*record.values, *[assumed[name] for name in missing]]
    return [edit.values.get(name, value) for name, value in zip(names, values)]


def apply(case: parse.Case, edits: Sequence[Edit]) -> str:
    """Return the text of the case with the edits made.

    Raises ValueError, with one problem on each line of its message, when
    any edit is not valid.
    """
    problems = check(case, edits)
    if problems:
        raise ValueError("\n".join(problems))
    lines = list(case.lines)
    removed = set()
    added = {case.ends[kind]: [] for kind in layouts.KINDS}
    ending = "\r\n" if lines[0].endswith("\r\n") else "\n"
    for edit in edits:
        layout = layouts.fields(case.version, edit.kind)
        if edit.removed:
            removed.add(edit.line)
        elif edit.line is None:
            texts = [_format(f, edit.values[f.name]) for f in layout]
            added[case.ends[edit.kind]].append(",".join(texts) + ending)
        elif edit.values:
            lines[edit.line] = _rewrite(
                lines[edit.line], layout, values_after(case, edit),
                edit.values)
    patched = []
    for index, line in enumerate(lines):
        patched += added.get(index, [])
        if index not in removed:
            patched.append(line)
    return "".join(patched)


def describe(case: parse.Case, edits: Sequence[Edit]) -> list[dict]:
    """Describe each edit for the record of a run, in plain values."""
    described = []
    for edit in edits:
        if edit.line is None:
            described.append({
                "kind": edit.kind,
                "action": "add",
                "record": label(edit.kind, values_after(case, edit)),
                "values": dict(edit.values),
            })
            continue
        record = case.record(edit.kind, edit.line)
        entry = {
            "kind": edit.kind,
            "action": "remove" if edit.removed else "change",
            "record": label(edit.kind, record.values),
            "line": edit.line + 1,
        }
        if not edit.removed:
            names = layouts.names(case.version, edit.kind)
            unchanged = values_after(case, Edit(edit.kind, edit.line))
            before = dict(zip(names, unchanged))
            entry["fields"] = {
                name: {"from": before[name], "to": value}
                for name, value in edit.values.items()
            }
        described.append(entry)
    return described


def summary(edits: Sequence[Edit]) -> str:
    """Count the edits, as in "1 added, 2 changed, 0 removed"."""
    added = sum(edit.line is None for edit in edits)
    removed = sum(edit.removed for edit in edits)
    changed = len(edits) - added - removed
    return f"{added} added, {changed} changed, {removed} removed"


def _check_edit(case: parse.Case, edit: Edit) -> list[str]:
    """Return the problems with one edit's kind, line, and values."""
    if edit.kind not in layouts.KINDS:
        return [f"A RAW case has no {edit.kind} records."]
    record = None if edit.line is None else case.record(edit.kind, edit.line)
    if edit.line is not None and record is None:
        return [f"Line {edit.line + 1} is not a {edit.kind} record."]
    layout = {f.name: f for f in layouts.fields(case.version, edit.kind)}
    # Name a record as the case has it, since an edit may change its ID.
    values = values_after(case, edit) if record is None else record.values
    name = label(edit.kind, values)
    problems = []
    if edit.line is None:
        problems += [
            f"{name}: {missing} has no value."
            for missing in layout
            if missing not in edit.values
        ]
    for field_name, value in edit.values.items():
        if field_name not in layout:
            problems.append(f"{name}: there is no field {field_name}.")
            continue
        problem = check_value(layout[field_name], value)
        if field_name in layouts.KEYS[edit.kind] and not value:
            problem = f"{field_name} must not be empty."
        if not problem and field_name == "X" and float(value) == 0.0:
            problem = "X must not be zero."
        if problem:
            problems.append(f"{name}: {problem}")
    return problems


def _check_keys(case: parse.Case, kind: str,
                edits: Sequence[Edit]) -> list[str]:
    """Return the problems with the buses and IDs of edited records.

    Every bus an edited or added record names must be in the case, and no
    two records of the kind may share their buses and ID once the edits are
    made.
    """
    counts = Counter(key(kind, record.values) for record in case.records[kind])
    touched = []
    for edit in edits:
        if edit.kind != kind:
            continue
        if edit.line is not None:
            counts[key(kind, case.record(kind, edit.line).values)] -= 1
        if not edit.removed:
            values = values_after(case, edit)
            counts[key(kind, values)] += 1
            touched.append(values)
    problems = []
    noun = "circuit" if kind == "branch" else "ID"
    for values in touched:
        name = label(kind, values)
        buses = values[:len(layouts.BUS_FIELDS[kind])]
        numbers = [parse.bus_number(text) for text in buses]
        for text, number in zip(buses, numbers):
            if number not in case.buses:
                problems.append(f"{name}: bus {text} is not in the case.")
        if kind == "branch" and numbers[0] == numbers[1]:
            problems.append(f"{name}: a branch needs two different buses.")
        if counts[key(kind, values)] > 1:
            problems.append(
                f"{name}: another {kind} has the same buses and {noun}.")
    return problems


def _rewrite(line: str, layout: Sequence[layouts.Field],
             values: Sequence[str], changes: dict[str, str]) -> str:
    """Rewrite the changed fields of a record's line in place.

    A changed field the line leaves out is added after its last field, with
    every field between them, so each lands in its position.
    """
    found = parse.spans(line)
    positions = [i for i, f in enumerate(layout) if f.name in changes]
    if positions[-1] >= len(found):
        extra = "".join(
            "," + _format(layout[i], values[i])
            for i in range(len(found), positions[-1] + 1))
        end = found[-1][1]
        line = line[:end] + extra + line[end:]
    for i in reversed(positions):
        if i < len(found):
            start, end = found[i]
            text = _format(layout[i], values[i], end - start)
            line = line[:start] + text + line[end:]
    return line


def _format(field: layouts.Field, value: str, width: int = 0) -> str:
    """Write a value as a RAW field.

    Text goes in single quotes, padded to its width as PSS/E writes it, since
    GridPACK cannot read an empty quoted name. A number is right-aligned in
    the width of the value it replaces, so the columns of a line stay put.
    """
    if field.kind == "text":
        return "'" + value.ljust(field.width) + "'"
    return value.rjust(width)


def _bus_text(text: str) -> str:
    """Return a bus field as its number without a sign, or as it is."""
    number = parse.bus_number(text)
    return text if number is None else str(number)
