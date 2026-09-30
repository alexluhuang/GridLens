"""The network of a RAW case: neighbourhoods, paths, islands, and the single outages that split it."""
from __future__ import annotations

from pathlib import Path

import pytest

from gridlens.analysis import topology
from gridlens.psse import parse


DATA = Path(__file__).parent / "data"

# A synthetic version 33 case. Area 1 is a ring 1-2-3-12-11-10-1 with two parallel circuits 1-2; a
# two-winding transformer 3-4 joins it to area 2, where branch 4-5 feeds bus 5, a three-winding
# transformer 4-6-7 feeds buses 6 and 7, branch 7-9 feeds bus 9, and branch 5-6 is out of service.
# Bus 8 is isolated, and branch 7-8 touches it.
TOPOLOGY_CASE = """ 0,   100.00, 33, 0, 0, 60.00     / synthetic topology case
SYNTHETIC TOPOLOGY CASE FOR GRIDLENS TESTS
NOT A REAL NETWORK
     1,'SWING       ', 230.0000,3,   1,   1,   1,1.00000,   0.0000
     2,'GEN         ', 230.0000,2,   1,   1,   1,1.00000,   0.0000
     3,'HUB         ', 230.0000,1,   1,   1,   1,1.00000,   0.0000
     4,'SOUTH HV    ', 138.0000,1,   2,   2,   1,1.00000,   0.0000
     5,'SOUTH A     ', 138.0000,1,   2,   2,   1,1.00000,   0.0000
     6,'TERTIARY    ',  13.8000,1,   2,   2,   1,1.00000,   0.0000
     7,'SOUTH LV    ',  69.0000,1,   2,   2,   1,1.00000,   0.0000
     8,'RETIRED     ',  69.0000,4,   2,   2,   1,1.00000,   0.0000
     9,'TOWN        ',  69.0000,1,   2,   2,   1,1.00000,   0.0000
    10,'RING A      ', 230.0000,1,   1,   1,   1,1.00000,   0.0000
    11,'RING B      ', 230.0000,1,   1,   1,   1,1.00000,   0.0000
    12,'RING C      ', 230.0000,1,   1,   1,   1,1.00000,   0.0000
0 / END OF BUS DATA, BEGIN LOAD DATA
     3,'1 ',1,   1,   1,    50.000,    10.000,     0.000,     0.000,     0.000,     0.000,   1,1,0
     9,'1 ',1,   2,   2,    10.000,     2.000,     0.000,     0.000,     0.000,     0.000,   1,1,0
     9,'2 ',0,   2,   2,    99.000,     2.000,     0.000,     0.000,     0.000,     0.000,   1,1,0
0 / END OF LOAD DATA, BEGIN FIXED SHUNT DATA
0 / END OF FIXED SHUNT DATA, BEGIN GENERATOR DATA
     1,'1 ',    30.000,     0.000,    99.000,   -99.000,1.00000,     0,   100.000, 0.0, 0.2, 0.0, 0.0,1.0,1,  100.0,   200.000,     0.000,   1,1.0000
     2,'1 ',    30.000,     0.000,    99.000,   -99.000,1.00000,     0,   100.000, 0.0, 0.2, 0.0, 0.0,1.0,1,  100.0,   200.000,     0.000,   1,1.0000
0 / END OF GENERATOR DATA, BEGIN BRANCH DATA
     1,     2,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
     1,     2,'2 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
     2,     3,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
     3,    12,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
    12,    11,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
    11,    10,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
    10,     1,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
     4,     5,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
     5,     6,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,0,1, 1.0,   1,1.0000
     7,     9,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
     7,     8,'1 ', 0.01, 0.05, 0.02,  100.00,  110.00,  120.00, 0.0, 0.0, 0.0, 0.0,1,1, 1.0,   1,1.0000
0 / END OF BRANCH DATA, BEGIN TRANSFORMER DATA
     4,     6,     7,'1 ',1,1,1, 0.0, 0.0,2,'THREE WIND  ',1,   1,1.0000
 0.001, 0.1, 100.0, 0.001, 0.1, 100.0, 0.001, 0.1, 100.0,1.0, 0.0
1.0, 0.0, 0.0, 100.0, 100.0, 100.0, 0, 0, 1.1, 0.9, 1.1, 0.9, 33, 0, 0.0, 0.0, 0.0
1.0, 0.0, 0.0, 100.0, 100.0, 100.0, 0, 0, 1.1, 0.9, 1.1, 0.9, 33, 0, 0.0, 0.0, 0.0
1.0, 0.0, 0.0, 100.0, 100.0, 100.0, 0, 0, 1.1, 0.9, 1.1, 0.9, 33, 0, 0.0, 0.0, 0.0
     3,     4,     0,'1 ',1,1,1, 0.0, 0.0,2,'TIE XFMR    ',1,   1,1.0000
 0.001, 0.1, 100.0
1.0, 0.0, 0.0, 100.0, 100.0, 100.0, 0, 0, 1.1, 0.9, 1.1, 0.9, 33, 0, 0.0, 0.0, 0.0
1.0, 0.0
0 / END OF TRANSFORMER DATA, BEGIN AREA DATA
     1,     1,     0.000,    10.000,'NORTH       '
     2,     1,     0.000,    10.000,'SOUTH       '
0 / END OF AREA DATA, BEGIN TWO-TERMINAL DC DATA
0 / END OF TWO-TERMINAL DC DATA
Q
"""


@pytest.fixture
def network() -> topology.Network:
    return topology.build_network(parse.parse_case(TOPOLOGY_CASE))


def labels(network: topology.Network, indexes: list[int]) -> list[str]:
    return [network.elements[index].label for index in indexes]


def test_transformers_and_areas_are_read_from_the_sections_after_the_branches():
    case = parse.parse_case(TOPOLOGY_CASE)
    three, two = parse.read_transformers(case)
    assert (three.i, three.j, three.k, three.circuit, three.status, three.name) == (4, 6, 7, "1", "1", "THREE WIND")
    assert (two.i, two.j, two.k, two.name) == (3, 4, 0, "TIE XFMR")
    assert parse.read_areas(case) == {1: "NORTH", 2: "SOUTH"}
    for version in (33, 34, 35):
        three_bus = parse.read_case(DATA / f"three_bus_v{version}.raw")
        assert parse.read_transformers(three_bus) == [] and parse.read_areas(three_bus) == {1: "NORTH", 2: "SOUTH"}


def test_the_network_leaves_out_isolated_buses_and_out_of_service_elements(network):
    assert 8 not in network.adjacency and not any(8 in (element.bus, element.end) for element in network.elements)
    assert "Branch 5 to 6 circuit 1" not in {element.label for element in network.elements}
    assert network.notes == [
        "1 buses are isolated (type 4), so they and the elements that touch them are not part of the network.",
        "1 branches and transformers are out of service in the case and are not part of the network.",
    ]
    # Out-of-service loads do not count toward a bus's load.
    assert network.load_mw == {3: 50.0, 9: 10.0} and network.generation_mw == {1: 30.0, 2: 30.0}


def test_a_three_winding_transformer_is_one_hop_between_its_buses(network):
    reached, via = topology.distances(network, [4], 1)
    assert reached == {4: 0, 3: 1, 5: 1, 6: 1, 7: 1}
    assert network.elements[via[6]].label == "Transformer 4-6-7 circuit 1, winding 2"
    reached, _ = topology.distances(network, [4], 2)
    assert reached == {4: 0, 3: 1, 5: 1, 6: 1, 7: 1, 2: 2, 12: 2, 9: 2}


def test_the_shortest_path_counts_elements_and_passes_through_the_star_point(network):
    assert labels(network, topology.shortest_path(network, 1, 9)) == [
        "Branch 1 to 2 circuit 1", "Branch 2 to 3 circuit 1", "Transformer 3 to 4 circuit 1",
        "Transformer 4-6-7 circuit 1, winding 1", "Transformer 4-6-7 circuit 1, winding 3", "Branch 7 to 9 circuit 1",
    ]
    assert topology.shortest_path(network, 9, 9) == []


def test_islands_are_the_connected_parts_of_the_network(network):
    (only,) = topology.islands(network)
    assert sorted(only.buses) == [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12] and only.swing_buses == 1
    cut = topology.build_network(parse.parse_case(TOPOLOGY_CASE.replace("     3,     4,     0,'1 ',1,1,1, 0.0, 0.0,2,'TIE XFMR    ',1,", "     3,     4,     0,'1 ',1,1,1, 0.0, 0.0,2,'TIE XFMR    ',0,")))
    north, south = topology.islands(cut)
    assert (sorted(north.buses), north.swing_buses, north.load_mw) == ([1, 2, 3, 10, 11, 12], 1, 50.0)
    assert (sorted(south.buses), south.swing_buses, south.load_mw) == ([4, 5, 6, 7, 9], 0, 10.0)


def test_splitting_outages_are_the_bridges_and_cut_off_the_smaller_part(network):
    splits = {network.elements[split.element].label: split for split in topology.splitting_outages(network)}
    assert set(splits) == {
        "Transformer 3 to 4 circuit 1", "Branch 4 to 5 circuit 1", "Branch 7 to 9 circuit 1",
        "Transformer 4-6-7 circuit 1, winding 1", "Transformer 4-6-7 circuit 1, winding 2", "Transformer 4-6-7 circuit 1, winding 3",
    }
    # Parallel circuits and a ring split nothing.
    assert not {"Branch 1 to 2 circuit 1", "Branch 1 to 2 circuit 2", "Branch 2 to 3 circuit 1"} & set(splits)
    tie = splits["Transformer 3 to 4 circuit 1"]
    assert (sorted(tie.islanded.buses), tie.islanded.load_mw, tie.islanded.swing_buses, len(tie.remaining.buses)) == ([4, 5, 6, 7, 9], 10.0, 0, 6)
    assert sorted(splits["Transformer 4-6-7 circuit 1, winding 3"].islanded.buses) == [7, 9]
    assert splits["Transformer 4-6-7 circuit 1, winding 2"].islanded.buses == [6]
    assert network.elements[splits["Branch 7 to 9 circuit 1"].element].outage == "BR_7_9_1"


def test_cutting_off_the_swing_bus_leaves_the_rest_without_one():
    """With bus 1 on one circuit, its outage cuts off the swing bus alone, and the other part has no swing bus."""
    radial = TOPOLOGY_CASE.replace("     1,     2,'2 '", "     2,    10,'2 '").replace("    10,     1,'1 '", "    10,     2,'1 '")
    network = topology.build_network(parse.parse_case(radial))
    split = next(item for item in topology.splitting_outages(network) if network.elements[item.element].label == "Branch 1 to 2 circuit 1")
    assert (split.islanded.buses, split.islanded.swing_buses, split.remaining.swing_buses, len(split.remaining.buses)) == ([1], 1, 0, 10)
