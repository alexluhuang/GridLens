"""The fields of load, generator, and branch records in PSS/E RAW cases.

Field order follows GridPACK's block parsers in ``src/parser/block_parsers``:
``load_parser33`` reads loads of every version, ``generator_parser33``,
``generator_parser34``, and ``generator_parser35`` read generators, and
``branch_parser33`` and ``branch_parser34`` read branches of version 33 and of
versions 34 and 35. Where GridPACK stops reading a record, as it does after
YQ in a load, the remaining fields and all defaults follow the PSS/E Program
Operation Manual, so every field of a record can be edited.
"""
from __future__ import annotations

from dataclasses import dataclass


VERSIONS = (33, 34, 35)
KINDS = ("load", "generator", "branch")

# The fields that identify a record, and the fields that name buses.
KEYS = {
    "load": ("I", "ID"),
    "generator": ("I", "ID"),
    "branch": ("I", "J", "CKT"),
}
BUS_FIELDS = {"load": ("I",), "generator": ("I",), "branch": ("I", "J")}


@dataclass(frozen=True)
class Field:
    """One field of a RAW record.

    kind is "int", "float", or "text". default is the value PSS/E assumes
    when the field is left out; it is empty for a field the user must enter,
    and for one whose default comes from the bus or the case. width is the
    most characters a text field may hold. gridpack is False for a field
    GridPACK does not read.
    """

    name: str
    kind: str
    default: str
    description: str
    width: int = 0
    gridpack: bool = True


def _owners() -> list[Field]:
    """Return the four owner number and fraction pairs that end a record."""
    owners = []
    for number, ordinal in enumerate(("First", "Second", "Third", "Fourth")):
        # PSS/E gives the first owner the bus's owner, and the others none.
        owner = "" if number == 0 else "0"
        owners += [
            Field(f"O{number + 1}", "int", owner, f"{ordinal} owner number"),
            Field(f"F{number + 1}", "float", "1.0",
                  f"{ordinal} owner's share of ownership"),
        ]
    return owners


def _loads(version: int) -> tuple[Field, ...]:
    """Return the fields of a load record."""
    status = "STATUS" if version == 33 else "STAT"
    fields = [
        Field("I", "int", "", "Bus number"),
        Field("ID", "text", "1", "Load identifier", width=2),
        Field(status, "int", "1", "1 in service, 0 out of service"),
        Field("AREA", "int", "", "Area number"),
        Field("ZONE", "int", "", "Zone number"),
        Field("PL", "float", "0.0", "Constant-power active load, MW"),
        Field("QL", "float", "0.0", "Constant-power reactive load, Mvar"),
        Field("IP", "float", "0.0",
              "Constant-current active load, MW at 1 pu voltage"),
        Field("IQ", "float", "0.0",
              "Constant-current reactive load, Mvar at 1 pu voltage"),
        Field("YP", "float", "0.0",
              "Constant-admittance active load, MW at 1 pu voltage"),
        Field("YQ", "float", "0.0",
              "Constant-admittance reactive load, Mvar at 1 pu voltage; "
              "negative for a capacitive load"),
        Field("OWNER", "int", "", "Owner number", gridpack=False),
        Field("SCALE", "int", "1",
              "1 if load scaling may change the load, 0 if it is fixed",
              gridpack=False),
        Field("INTRPT", "int", "0", "1 if the load is interruptible",
              gridpack=False),
    ]
    if version >= 34:
        mode = "DGENF" if version == 34 else "DGENM"
        fields += [
            Field("DGENP", "float", "0.0", "Distributed generation, MW",
                  gridpack=False),
            Field("DGENQ", "float", "0.0", "Distributed generation, Mvar",
                  gridpack=False),
            Field(mode, "int", "0", "Distributed generation: 1 on, 0 off",
                  gridpack=False),
        ]
    if version == 35:
        fields.append(Field("LOADTYPE", "text", "", "Load type", width=12,
                            gridpack=False))
    return tuple(fields)


def _generators(version: int) -> tuple[Field, ...]:
    """Return the fields of a generator record.

    Version 34 appends NREG to the version 33 record; version 35 moves NREG
    after IREG and adds BASLOD after PB, as GridPACK's parsers read them.
    """
    nreg = Field("NREG", "int", "0",
                 "Node of the regulated bus whose voltage is held; 0 for none")
    fields = [
        Field("I", "int", "", "Bus number"),
        Field("ID", "text", "1", "Machine identifier", width=2),
        Field("PG", "float", "0.0", "Active power output, MW"),
        Field("QG", "float", "0.0", "Reactive power output, Mvar"),
        Field("QT", "float", "9999.0", "Maximum reactive power, Mvar"),
        Field("QB", "float", "-9999.0", "Minimum reactive power, Mvar"),
        Field("VS", "float", "1.0", "Voltage setpoint, pu"),
        Field("IREG", "int", "0",
              "Bus whose voltage the machine holds; 0 for its own bus"),
    ]
    if version == 35:
        fields.append(nreg)
    fields += [
        Field("MBASE", "float", "", "Machine base, MVA"),
        Field("ZR", "float", "0.0", "Machine resistance, pu on MBASE"),
        Field("ZX", "float", "1.0", "Machine reactance, pu on MBASE"),
        Field("RT", "float", "0.0",
              "Step-up transformer resistance, pu on MBASE"),
        Field("XT", "float", "0.0",
              "Step-up transformer reactance, pu on MBASE"),
        Field("GTAP", "float", "1.0",
              "Step-up transformer off-nominal turns ratio, pu"),
        Field("STAT", "int", "1", "1 in service, 0 out of service"),
        Field("RMPCT", "float", "100.0",
              "Percent of the Mvar needed to hold the regulated bus's "
              "voltage that this machine supplies"),
        Field("PT", "float", "9999.0", "Maximum active power, MW"),
        Field("PB", "float", "-9999.0", "Minimum active power, MW"),
    ]
    if version == 35:
        fields.append(Field("BASLOD", "int", "0",
                            "Base load: 0 dispatchable, 1 not down, "
                            "2 not up, 3 neither"))
    fields += _owners()
    fields += [
        Field("WMOD", "int", "0",
              "Control mode: 0 conventional, 1 to 4 wind and inverter modes"),
        Field("WPF", "float", "1.0", "Power factor for WMOD 1 to 3"),
    ]
    if version == 34:
        fields.append(nreg)
    return tuple(fields)


def _branches(version: int) -> tuple[Field, ...]:
    """Return the fields of a non-transformer branch record.

    Versions 34 and 35 add NAME after B and carry 12 ratings in place of
    RATEA, RATEB, and RATEC.
    """
    fields = [
        Field("I", "int", "", "From bus number"),
        Field("J", "int", "", "To bus number"),
        Field("CKT", "text", "1", "Circuit identifier", width=2),
        Field("R", "float", "0.0", "Resistance, pu"),
        Field("X", "float", "", "Reactance, pu; must not be zero"),
        Field("B", "float", "0.0", "Total line charging, pu"),
    ]
    if version == 33:
        fields += [
            Field(f"RATE{letter}", "float", "0.0", f"Rating {letter}, MVA")
            for letter in "ABC"
        ]
    else:
        fields.append(Field("NAME", "text", "", "Branch name", width=40))
        fields += [
            Field(f"RATE{number}", "float", "0.0", f"Rating {number}, MVA")
            for number in range(1, 13)
        ]
    fields += [
        Field("GI", "float", "0.0", "Shunt conductance at the from bus, pu"),
        Field("BI", "float", "0.0", "Shunt susceptance at the from bus, pu"),
        Field("GJ", "float", "0.0", "Shunt conductance at the to bus, pu"),
        Field("BJ", "float", "0.0", "Shunt susceptance at the to bus, pu"),
        Field("ST" if version == 33 else "STAT", "int", "1",
              "1 in service, 0 out of service"),
        Field("MET", "int", "1", "Metered end: 1 from bus, 2 to bus"),
        Field("LEN", "float", "0.0", "Line length, in the case's units"),
    ]
    return tuple(fields + _owners())


_BUILDERS = {"load": _loads, "generator": _generators, "branch": _branches}
_LAYOUTS = {
    (version, kind): build(version)
    for version in VERSIONS
    for kind, build in _BUILDERS.items()
}


def fields(version: int, kind: str) -> tuple[Field, ...]:
    """Return the fields of a kind of record in a case of a RAW version.

    kind is "load", "generator", or "branch"; version is 33, 34, or 35.
    """
    return _LAYOUTS[(version, kind)]


def names(version: int, kind: str) -> list[str]:
    """Return the field names of a kind of record, in file order."""
    return [field.name for field in fields(version, kind)]
