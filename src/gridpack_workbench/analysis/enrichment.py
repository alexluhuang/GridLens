from __future__ import annotations

from gridpack_workbench.analysis.parser_models import ParsedTable
from gridpack_workbench.analysis.table_helpers import append_missing_columns, as_float, float_or_zero


BUS_METADATA_TABLES = (
    "vmag",
    "vang",
    "vmag_mm",
    "vang_mm",
    "pq_change_cnt",
    "pgen",
    "qgen",
    "pgen_mm",
    "qgen_mm",
)

BRANCH_METADATA_TABLES = ("branch_metadata", "pflow", "qflow", "pflow_mm", "qflow_mm", "perf_mm", "line_flt_cnt")

__all__ = ["enrich_with_bus_metadata", "voltage_class"]


def enrich_with_bus_metadata(tables: dict[str, ParsedTable]) -> None:
    """Add bus, area, and voltage-class context to parsed GridPACK output tables."""
    metadata = tables.get("bus_metadata")
    if not metadata or not metadata.rows:
        return

    buses = {bus_id: row for row in metadata.rows if (bus_id := _bus_id(row, "bus_id")) is not None}
    _enrich_bus_tables(tables, buses)
    _enrich_branch_tables(tables, buses)


def voltage_class(base_kv: object) -> str:
    """Map a bus base voltage to a coarse transmission voltage class."""
    kv = as_float(base_kv)
    if kv is None:
        return "unknown"
    if kv < 100:
        return "<100 kV"
    if kv < 230:
        return "100-229 kV"
    if kv < 345:
        return "230-344 kV"
    if kv < 500:
        return "345-499 kV"
    return "500+ kV"


def _enrich_bus_tables(tables: dict[str, ParsedTable], buses: dict[int, dict[str, object]]) -> None:
    for table_name in BUS_METADATA_TABLES:
        table = tables.get(table_name)
        if not table:
            continue
        for row in table.rows:
            bus = buses.get(_bus_id(row, "bus_id"))
            if bus:
                row.update(
                    {
                        "bus_name": bus.get("bus_name", ""),
                        "base_kv": bus.get("base_kv"),
                        "area": bus.get("area"),
                        "zone": bus.get("zone"),
                        "voltage_class": voltage_class(bus.get("base_kv")),
                    }
                )
        append_missing_columns(table, ["bus_name", "base_kv", "area", "zone", "voltage_class"])


def _enrich_branch_tables(tables: dict[str, ParsedTable], buses: dict[int, dict[str, object]]) -> None:
    for table_name in BRANCH_METADATA_TABLES:
        table = tables.get(table_name)
        if not table:
            continue
        for row in table.rows:
            from_bus = buses.get(_bus_id(row, "from_bus"))
            to_bus = buses.get(_bus_id(row, "to_bus"))
            from_kv = from_bus.get("base_kv") if from_bus else None
            to_kv = to_bus.get("base_kv") if to_bus else None
            from_area = from_bus.get("area") if from_bus else None
            to_area = to_bus.get("area") if to_bus else None
            row.update(
                {
                    "from_bus_name": from_bus.get("bus_name", "") if from_bus else "",
                    "to_bus_name": to_bus.get("bus_name", "") if to_bus else "",
                    "from_base_kv": from_kv,
                    "to_base_kv": to_kv,
                    "from_area": from_area,
                    "to_area": to_area,
                    "area": _area_label(from_area, to_area),
                    "voltage_class": voltage_class(max(float_or_zero(from_kv), float_or_zero(to_kv)) or None),
                }
            )
        append_missing_columns(
            table,
            [
                "from_bus_name",
                "to_bus_name",
                "from_base_kv",
                "to_base_kv",
                "from_area",
                "to_area",
                "area",
                "voltage_class",
            ],
        )


def _area_label(from_area: object, to_area: object) -> str:
    if from_area in (None, "") and to_area in (None, ""):
        return "unknown"
    if from_area == to_area:
        return str(from_area)
    return f"{from_area}-{to_area}"


def _bus_id(row: dict[str, object], column: str) -> int | None:
    try:
        return int(row[column])
    except (KeyError, TypeError, ValueError):
        return None
