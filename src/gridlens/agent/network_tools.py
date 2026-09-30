"""The topology tool: how a case's network is connected, read from its RAW file.

The analysis tools answer from GridPACK's results; this one answers from the case itself, through
`gridlens.analysis.topology`: which buses or elements lie within some number of elements of a bus, the
shortest path between two buses, the islands of the network, and the single outages that split it. With a
run, the splitting outages also carry the status GridPACK gave each of them, so a model can say which
outages GridPACK could not solve because they island part of the system, and which it solved without the
buses they cut off.
"""
from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
from typing import Literal

from gridlens.agent.policy import AgentError
from gridlens.agent.session import PROJECT_FILE, read_json, scoped_path
from gridlens.agent.tool_base import ToolBase, tool
from gridlens.analysis import topology
from gridlens.core import sensitivity
from gridlens.core.project import ProjectData
from gridlens.psse import changes, parse


NETWORK_TOOL_NAMES = ("topology",)
TopologyQuery = Literal["buses_near", "elements_near", "path", "islands", "islanding_outages"]
OutageOrder = Literal["load_mw", "generation_mw", "bus_count"]
# How islanding_outages sorts, largest first, by what the outage cuts off.
ORDER_KEYS = {"load_mw": "cut_off_load_mw", "generation_mw": "cut_off_generation_mw", "bus_count": "cut_off_bus_count"}
MAX_HOPS = 20
MAX_CONVERGENCE_BYTES = 64 * 1024 * 1024


def _collapsed(network: topology.Network, indexes: list[int]) -> list[list[int]]:
    """Group element indexes so the windings of one three-winding transformer count as one element."""
    groups: dict[object, list[int]] = {}
    for index in indexes:
        element = network.elements[index]
        key = ("transformer", element.transformer) if element.kind == "transformer winding" else ("element", index)
        groups.setdefault(key, []).append(index)
    return list(groups.values())


def _label(network: topology.Network, indexes: list[int]) -> str:
    """Name an element, or a three-winding transformer from any of its windings."""
    return network.elements[indexes[0]].label.rsplit(", winding", 1)[0]


def _element_row(network: topology.Network, indexes: list[int]) -> dict:
    """Describe one element, or one three-winding transformer, for a result row."""
    first = network.elements[indexes[0]]
    buses = sorted({network.elements[index].bus for index in indexes}) if first.kind == "transformer winding" else [first.bus, first.end]
    row = {
        "element": _label(network, indexes), "kind": "three-winding transformer" if first.kind == "transformer winding" else first.kind,
        "circuit": first.circuit, "buses": buses, "gridpack_contingency": first.outage or None,
    }
    for position, bus in enumerate(buses[:3], 1):
        described = network.bus_row(bus)
        row[f"bus_{position}_name"] = described["bus_name"]
        row[f"bus_{position}_kv"] = described["base_kv"]
        row[f"bus_{position}_area"] = network.area_label(bus)
    return row


class NetworkTools(ToolBase):
    """The topology tool, bound to one session."""

    def _case(self, run_id: str, project: str) -> tuple[parse.Case, Path, Path | None]:
        """Read the case of a run, which for a sensitivity run is its edited case, or else the project's case."""
        if run_id:
            run = self._run(run_id, project, completed=False)
            manifest = self._json(run, "manifest.json")
            if not manifest.get("xml_file"):
                raise AgentError("NO_CONFIGURATION", "The run's manifest names no XML configuration, so its case is unknown.")
            xml = self._source(scoped_path(run, Path("work") / manifest["xml_file"]), run)
            path = self._source(scoped_path(run, Path("work") / sensitivity.network_file(xml)), run)
        else:
            root = self._project(project)
            try:
                data = ProjectData.from_dict(read_json(scoped_path(root, PROJECT_FILE)))
            except (KeyError, TypeError) as exc:
                raise AgentError("INVALID_PROJECT", "This project's project.json is incomplete. Open and save the project in the Project tab.") from exc
            path = self._source(scoped_path(root, Path("original_inputs") / sensitivity.base_case(data).name), root)
            run = None
        try:
            return parse.read_case(path), path, run
        except ValueError as exc:
            raise AgentError("UNSUPPORTED_CASE", f"{path.name} cannot be read as a PSS/E RAW case: {exc}") from exc

    def _statuses(self, run: Path) -> dict[str, str] | None:
        """Return GridPACK's status for each contingency of a run by name, or None when it has no convergence file."""
        paths = sorted(scoped_path(run, "work", directory=True).glob("*convergence*.csv"))
        if not paths:
            return None
        path = self._source(paths[0], run)
        if path.stat().st_size > MAX_CONVERGENCE_BYTES:
            raise AgentError("ARTIFACT_TOO_LARGE", "The convergence file exceeds the read limit.")
        with path.open(encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"contingency", "status_code"}.issubset(reader.fieldnames or ()):
                raise AgentError("INVALID_ARTIFACT", "The convergence CSV has no contingency and status_code columns.")
            return {str(row["contingency"]).strip(): str(row["status_code"] or "").strip() for row in reader}

    @tool
    def topology(self, query: TopologyQuery, bus: int = 0, to_bus: int = 0, hops: int = 1, area: str = "", order_by: OutageOrder = "load_mw", run_id: str = "", project: str = "", offset: int = 0, limit: int = 100) -> dict:
        """Answer how the case's network is connected, from its RAW file: buses_near lists the buses within hops elements of bus (or of both ends of the branch bus to to_bus), with how each was reached; elements_near lists the branches and transformers whose buses are all within hops; path gives the shortest route from bus to to_bus, by number of elements; islands lists the network's islands; islanding_outages lists every single branch or transformer outage that splits the network, with the smaller part it cuts off (its buses and their in-service load and generation in MW) and whether each part keeps a swing bus, largest first by order_by: cut-off load_mw (the default), generation_mw, or bus_count. The case is run_id's, which for a sensitivity run is its edited case, or else the project's. With run_id, islanding_outages also gives GridPACK's status for each outage in that run (ISLANDED, or OK when GridPACK solved the case without the buses cut off). area (number or name) keeps islands and outages that touch that area. Only in-service AC branches and transformers join buses; DC lines and switching devices do not."""
        if isinstance(hops, bool) or not isinstance(hops, int) or not 0 <= hops <= MAX_HOPS:
            raise AgentError("INVALID_HOPS", f"hops must be a whole number from 0 to {MAX_HOPS}.")
        case, path, run = self._case(run_id, project)
        network = topology.build_network(case)
        self.warnings.extend(network.notes)
        wanted_area = self._area(case, area)
        header = {"query": query, "case": str(path), "network": {"buses": sum(1 for node in network.adjacency if node > 0), "elements": len(_collapsed(network, list(range(len(network.elements)))))}}
        if query in ("buses_near", "elements_near", "path"):
            start = self._buses(network, [bus] + ([to_bus] if to_bus and query != "path" else []))
        if query == "buses_near":
            reached, via = topology.distances(network, start, hops)
            rows = [
                {**network.bus_row(number), "area": network.area_label(number), "hops": depth, "reached_by": _label(network, [via[number]]) if number in via else None}
                for number, depth in sorted(reached.items(), key=lambda item: (item[1], item[0]))
            ]
            return {**header, "start": start, "hops": hops, "rows": rows}
        if query == "elements_near":
            reached, _ = topology.distances(network, start, hops)
            rows = []
            # Every winding of a three-winding transformer is grouped first, so it is kept only when all its buses are near.
            for indexes in _collapsed(network, list(range(len(network.elements)))):
                if network.elements[indexes[0]].bus not in reached:
                    continue
                row = _element_row(network, indexes)
                if all(number in reached for number in row["buses"]):
                    rows.append({**row, "hops": max(reached[number] for number in row["buses"])})
            rows.sort(key=lambda row: (row["hops"], row["buses"], row["circuit"]))
            return {**header, "start": start, "hops": hops, "rows": rows}
        if query == "path":
            goal = self._buses(network, [to_bus])[0] if to_bus else None
            if goal is None:
                raise AgentError("MISSING_BUS", "path needs bus and to_bus.")
            route = topology.shortest_path(network, start[0], goal)
            if route is None:
                raise AgentError("NO_PATH", f"No in-service elements join bus {start[0]} to bus {goal}; they are in different islands.")
            rows, here = [], start[0]
            for indexes in _collapsed(network, route):
                row = _element_row(network, indexes)
                ends = [network.elements[index].bus for index in indexes] if row["kind"] == "three-winding transformer" else row["buses"]
                there = next(number for number in ends if number != here)
                rows.append({"step": len(rows) + 1, "from_bus": here, "from_name": network.bus_row(here)["bus_name"], "to_bus": there, "to_name": network.bus_row(there)["bus_name"], **row})
                here = there
            return {**header, "from_bus": start[0], "to_bus": goal, "elements_on_path": len(rows), "rows": rows}
        if query == "islands":
            rows = []
            for number, part in enumerate(topology.islands(network), 1):
                if wanted_area is None or any(network.buses[item].area == str(wanted_area) for item in part.buses):
                    rows.append({"island": number, **network.part_row(part)})
            return {**header, "island_count": len(topology.islands(network)), "rows": rows}
        if query == "islanding_outages":
            if order_by not in ORDER_KEYS:
                raise AgentError("INVALID_ORDER", "Choose order_by from: load_mw, generation_mw, bus_count.")
            return {**header, **self._islanding(network, run, wanted_area, order_by)}
        raise AgentError("INVALID_QUERY", "Choose query from: buses_near, elements_near, path, islands, islanding_outages.")

    def _islanding(self, network: topology.Network, run: Path | None, area: int | None, order_by: str) -> dict:
        """List the outages that split the network, with GridPACK's status for each when a run is given."""
        statuses = self._statuses(run) if run is not None else None
        if run is not None and statuses is None:
            self.warnings.append("The run has no convergence file, so GridPACK's status for each outage is unknown.")
        rows = []
        found = set()
        for split in topology.splitting_outages(network):
            element = network.elements[split.element]
            if area is not None and not {network.buses[element.bus].area, network.buses[element.end].area if element.end > 0 else ""} & {str(area)}:
                continue
            names = [element.outage, f"BR_{element.end}_{element.bus}_{element.circuit}"] if element.outage else []
            found.update(names)
            cut_off = network.part_row(split.islanded)
            row = {
                "outage": element.label, "kind": element.kind, "from_bus": element.bus, "to_bus": element.end if element.end > 0 else None,
                "circuit": element.circuit, "gridpack_contingency": element.outage or None,
                **{f"cut_off_{key}": value for key, value in cut_off.items()},
                "remaining_bus_count": len(split.remaining.buses), "remaining_has_swing_bus": split.remaining.swing_buses > 0,
            }
            if statuses is not None:
                row["gridpack_status"] = next((statuses[name] for name in names if name in statuses), None)
            rows.append(row)
        key = ORDER_KEYS[order_by]
        rows.sort(key=lambda row: (-row[key], -row["cut_off_load_mw"], -row["cut_off_bus_count"], row["outage"]))
        result = {
            "rows": rows, "order_by": order_by,
            "definition": "single outages of one in-service branch, transformer, or transformer winding that leave some buses joined to the rest of the network by no in-service element",
            # An outage that cuts off a swing bus leaves the rest of the network without one, whatever it cuts off.
            "swing_bus_outages": [row["outage"] for row in rows if row["cut_off_has_swing_bus"]],
        }
        if statuses is not None:
            result["gridpack_status_counts"] = dict(Counter(row["gridpack_status"] or "not in this run" for row in rows))
            missed = sorted(name for name, status in statuses.items() if status == "ISLANDED" and name not in found)
            if area is None:
                result["islanded_in_run_but_not_found"] = missed
                if missed:
                    self.warnings.append(f"GridPACK reported {len(missed)} ISLANDED contingencies that split nothing in this case's AC network, such as {', '.join(missed[:5])}; the case may have changed, or GridPACK models an element differently.")
        return result

    def _buses(self, network: topology.Network, numbers: list[object]) -> list[int]:
        """Return bus numbers as the network has them, refusing a bus that is not in the case or not in service."""
        found = []
        for value in numbers:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise AgentError("MISSING_BUS", "Give bus (and to_bus where needed) as a bus number from the case.")
            if value not in network.buses:
                raise AgentError("UNKNOWN_BUS", f"Bus {value} is not in the case.")
            if value not in network.adjacency:
                raise AgentError("ISOLATED_BUS", f"Bus {value} is isolated (type 4), so no element joins it to the network.")
            found.append(value)
        return found

    def _area(self, case: parse.Case, area: str) -> int | None:
        """Return the area number an area argument gives, by number or by the case's area name, or None."""
        text = str(area or "").strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        try:
            return changes.area_number(case, text)
        except changes.ChangeError as exc:
            raise AgentError("UNKNOWN_AREA", str(exc)) from exc
