"""The connectivity of a PSS/E RAW case: which buses its in-service branches and transformers join.

GridPACK's contingency analysis solves each outage as a power flow. An outage that splits the network
leaves part of it without a swing bus, and GridPACK reports that contingency as ISLANDED rather than
solving it. The flows say nothing about the network's shape, so this module answers those questions from
the case itself: which buses and elements lie within some number of elements of a bus, the shortest path
between two buses, the islands of the case as it stands, and the single outages that split it.

The network holds the case's in-service AC elements: non-transformer branches, and two- and three-winding
transformers. A three-winding transformer joins its in-service windings' buses through a star point, as
GridPACK models it, so a path through it counts as one element. Isolated buses (type 4) and the elements
that touch them are left out, as GridPACK leaves them out. DC lines, FACTS devices, and, in versions 34
and 35, system switching devices are not part of the network; `Network.notes` says when a case has any.

An outage is one element, as GridPACK's branch contingencies are: one circuit of a pair of parallel
circuits leaves the other joining its buses, so it splits nothing.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from gridlens.psse import layouts, parse


# How many buses of an island or an islanded part a result names; the counts and totals cover all of them.
LISTED_BUSES = 10


@dataclass(frozen=True)
class Element:
    """One in-service element of the network, or one winding of a three-winding transformer.

    end is the other end of the element: a bus, or, for a winding, the transformer's star point, a
    negative node number. outage is GridPACK's name for the contingency that takes the element out,
    BR_<from>_<to>_<circuit>, or "" for a winding, whose contingency name depends on how GridPACK numbers
    the star point.
    """

    kind: str
    bus: int
    end: int
    circuit: str
    label: str
    outage: str
    transformer: int | None = None


@dataclass
class Part:
    """Some buses of the network with their in-service load and generation."""

    buses: list[int] = field(default_factory=list)
    load_mw: float = 0.0
    generation_mw: float = 0.0
    swing_buses: int = 0


@dataclass
class Network:
    """The in-service AC network of a case: buses, elements, and which elements meet at each node."""

    buses: dict[int, parse.Bus]
    area_names: dict[str, str]
    elements: list[Element]
    adjacency: dict[int, list[tuple[int, int]]]
    load_mw: dict[int, float]
    generation_mw: dict[int, float]
    notes: list[str]

    def bus_row(self, number: int) -> dict:
        """Describe a bus for a result row: number, name, voltage, type, area, and zone."""
        bus = self.buses[number]
        return {
            "bus": number, "bus_name": bus.name.strip(), "base_kv": _float(bus.base_kv), "type": int(bus.ide) if bus.ide.isdigit() else bus.ide,
            "area": _int(bus.area), "area_name": self.area_names.get(bus.area, "").strip(), "zone": _int(bus.zone),
        }

    def area_label(self, number: int) -> str:
        """Return a bus's area as its number and name, such as "7 Coast"."""
        area = self.buses[number].area
        return f"{area} {self.area_names.get(area, '').strip()}".strip()

    def part(self, buses: Iterable[int]) -> Part:
        """Return the buses among nodes, with their load, generation, and swing bus count."""
        part = Part()
        for node in buses:
            if node > 0:
                part.buses.append(node)
                part.load_mw += self.load_mw.get(node, 0.0)
                part.generation_mw += self.generation_mw.get(node, 0.0)
                part.swing_buses += self.buses[node].ide == "3"
        return part

    def part_row(self, part: Part) -> dict:
        """Describe some buses for a result row: how many, their areas, load, generation, and the first few."""
        areas = sorted({self.area_label(bus) for bus in part.buses}, key=lambda text: (len(text.split(" ", 1)[0]), text))
        return {
            "bus_count": len(part.buses), "load_mw": round(part.load_mw, 3), "generation_mw": round(part.generation_mw, 3),
            "has_swing_bus": part.swing_buses > 0, "areas": areas,
            "buses": [f"{bus} {self.buses[bus].name.strip()}".strip() for bus in sorted(part.buses)[:LISTED_BUSES]],
        }


def build_network(case: parse.Case) -> Network:
    """Return the in-service AC network of a case."""
    try:
        area_names = {str(number): name for number, name in parse.read_areas(case).items()}
    except ValueError:
        area_names = {}
    notes = []
    isolated = {number for number, bus in case.buses.items() if bus.ide == "4"}
    if isolated:
        notes.append(f"{len(isolated):,} buses are isolated (type 4), so they and the elements that touch them are not part of the network.")
    elements: list[Element] = []
    branch_names = layouts.names(case.version, "branch")
    status = branch_names.index(next(name for name in ("ST", "STAT") if name in branch_names))
    out_of_service = 0
    for record in case.records["branch"]:
        i, j = parse.bus_number(record.values[0]), parse.bus_number(record.values[1])
        circuit = record.values[2] if len(record.values) > 2 else "1"
        if (record.values[status] if len(record.values) > status else "1") == "0":
            out_of_service += 1
            continue
        if _usable(case, isolated, i, j):
            elements.append(Element("branch", i, j, circuit, f"Branch {i} to {j} circuit {circuit}", f"BR_{i}_{j}_{circuit}"))
    transformers = parse.read_transformers(case)
    star = 0
    for index, transformer in enumerate(transformers):
        if transformer.status == "0":
            out_of_service += 1
            continue
        if not transformer.k:
            if _usable(case, isolated, transformer.i, transformer.j):
                elements.append(Element(
                    "transformer", transformer.i, transformer.j, transformer.circuit,
                    f"Transformer {transformer.i} to {transformer.j} circuit {transformer.circuit}",
                    f"BR_{transformer.i}_{transformer.j}_{transformer.circuit}", index,
                ))
            continue
        star -= 1
        name = f"Transformer {transformer.i}-{transformer.j}-{transformer.k} circuit {transformer.circuit}"
        # STAT 2, 3, and 4 take winding 2, 3, or 1 out of service.
        off = {"2": 2, "3": 3, "4": 1}.get(transformer.status)
        for winding, bus in enumerate((transformer.i, transformer.j, transformer.k), 1):
            if winding != off and _usable(case, isolated, bus):
                elements.append(Element("transformer winding", bus, star, transformer.circuit, f"{name}, winding {winding}", "", index))
    if out_of_service:
        notes.append(f"{out_of_service:,} branches and transformers are out of service in the case and are not part of the network.")
    extra = _unmodeled(case)
    if extra:
        notes.append(extra)
    adjacency: dict[int, list[tuple[int, int]]] = {number: [] for number in case.buses if number not in isolated}
    for index, element in enumerate(elements):
        adjacency.setdefault(element.bus, []).append((element.end, index))
        adjacency.setdefault(element.end, []).append((element.bus, index))
    return Network(case.buses, area_names, elements, adjacency, _in_service(case, "load", "PL"), _in_service(case, "generator", "PG"), notes)


def distances(network: Network, start: Sequence[int], hops: int) -> tuple[dict[int, int], dict[int, int]]:
    """Return the buses within hops elements of the start buses, with the element each was reached by.

    A three-winding transformer counts as one element between its windings' buses. Returns (hops away by
    bus, element index by node): a start bus has 0 hops and no element, and a star point, a negative node,
    is listed with the winding that reached it, so a path can be traced back through it.
    """
    reached = {bus: 0 for bus in start}
    via: dict[int, int] = {}
    queue = deque((bus, 0) for bus in start)
    while queue:
        node, depth = queue.popleft()
        for neighbour, element in network.adjacency.get(node, ()):
            step = depth if neighbour < 0 else depth + 1
            if step > hops or reached.get(neighbour, hops + 1) <= step:
                continue
            reached[neighbour] = step
            via[neighbour] = element
            # Reaching a star point is free, so it goes first, keeping the queue in order of hops.
            (queue.appendleft if neighbour < 0 else queue.append)((neighbour, step))
    return {bus: depth for bus, depth in reached.items() if bus > 0}, via


def shortest_path(network: Network, start: int, goal: int) -> list[int] | None:
    """Return the element indexes of a path from start to goal with the fewest elements, or None."""
    reached, via = distances(network, [start], len(network.adjacency) + 1)
    if goal not in reached:
        return None
    path = []
    node = goal
    while node != start:
        element = via[node]
        path.append(element)
        item = network.elements[element]
        node = item.bus if item.end == node else item.end
        if node < 0:
            # A star point: step back through the winding that reached it.
            winding = via[node]
            path.append(winding)
            item = network.elements[winding]
            node = item.bus if item.end == node else item.end
    return list(reversed(path))


def islands(network: Network) -> list[Part]:
    """Return the network's islands, largest first."""
    seen: set[int] = set()
    found = []
    for node in network.adjacency:
        if node in seen or node < 0:
            continue
        members = []
        stack = [node]
        seen.add(node)
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbour, _ in network.adjacency.get(current, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        found.append(network.part(members))
    return sorted(found, key=lambda part: (-len(part.buses), min(part.buses)))


@dataclass(frozen=True)
class Split:
    """One outage that splits the network: the element, the buses it cuts off, and the part that remains."""

    element: int
    islanded: Part
    remaining: Part


def splitting_outages(network: Network) -> list[Split]:
    """Return every single-element outage that splits the network, with the part it cuts off.

    These are the bridges of the network's graph, found in one depth-first search (Tarjan's method),
    counting parallel circuits as separate elements. The part cut off is the smaller one, or the one
    without a swing bus when both are the same size. When the part cut off holds the swing bus, as when a
    swing generator's only step-up transformer is out, the rest of the network is the part left without one.
    """
    entry: dict[int, int] = {}
    low: dict[int, int] = {}
    order: list[int] = []
    span: dict[int, int] = {}
    bridges: list[tuple[int, int, int]] = []  # (element, child node, root of its component)
    components: dict[int, tuple[int, int]] = {}  # root: (first position in order, node count)
    for root in network.adjacency:
        if root in entry:
            continue
        entry[root] = low[root] = len(order)
        order.append(root)
        stack = [(root, -1, iter(network.adjacency[root]))]
        while stack:
            node, arrived_by, neighbours = stack[-1]
            for neighbour, element in neighbours:
                if element == arrived_by:
                    continue
                if neighbour in entry:
                    low[node] = min(low[node], entry[neighbour])
                    continue
                entry[neighbour] = low[neighbour] = len(order)
                order.append(neighbour)
                stack.append((neighbour, element, iter(network.adjacency[neighbour])))
                break
            else:
                stack.pop()
                span[node] = len(order) - entry[node]
                if stack:
                    parent = stack[-1][0]
                    low[parent] = min(low[parent], low[node])
                    if low[node] > entry[parent]:
                        bridges.append((arrived_by, node, root))
        components[root] = (entry[root], len(order) - entry[root])
    splits = []
    for element, child, root in bridges:
        start, count = entry[child], span[child]
        first, size = components[root]
        below = network.part(order[start:start + count])
        rest = network.part(order[first:start] + order[start + count:first + size])
        islanded, remaining = sorted((below, rest), key=lambda part: (len(part.buses), part.swing_buses))
        # A winding whose transformer has no other winding in service cuts off only the star point.
        if islanded.buses:
            splits.append(Split(element, islanded, remaining))
    return splits


def _usable(case: parse.Case, isolated: set[int], *buses: int | None) -> bool:
    """Return whether every bus of an element is in the case and not isolated."""
    return all(bus is not None and bus in case.buses and bus not in isolated for bus in buses)


def _in_service(case: parse.Case, kind: str, quantity: str) -> dict[int, float]:
    """Return the in-service total of a load or generator field at each bus, such as PL or PG."""
    names = layouts.names(case.version, kind)
    status = names.index(next(name for name in ("STATUS", "STAT") if name in names))
    column = names.index(quantity)
    totals: dict[int, float] = {}
    for record in case.records[kind]:
        values = record.values
        if (values[status] if len(values) > status else "1") != "1":
            continue
        bus = parse.bus_number(values[0])
        if bus is not None:
            totals[bus] = totals.get(bus, 0.0) + _float(values[column] if len(values) > column else "0")
    return totals


def _unmodeled(case: parse.Case) -> str:
    """Name the elements of a case that join buses but are not part of the network, or return ""."""
    counts = []
    try:
        sections = parse.later_sections(case)
    except ValueError:
        return ""
    switching = sections.get("system switching device")
    if switching:
        count = sum(1 for index in range(*switching) if case.lines[index].strip() and not case.lines[index].lstrip().startswith(("@!", "//")))
        if count:
            counts.append(f"{count:,} system switching devices")
    return (", ".join(counts) + " are in the case but not part of this network.") if counts else ""


def _float(text: object) -> float:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return 0.0


def _int(text: object) -> int | str:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return str(text)
