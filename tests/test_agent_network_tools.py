"""The topology tool reads a project's or a run's case and answers how its network is connected."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridlens.agent.session import SessionContext
from gridlens.agent.tools import ToolService

from test_topology import TOPOLOGY_CASE


@pytest.fixture
def study(tmp_path):
    """Return tools for a project of the synthetic topology case, with a run of it and of an edited copy."""
    inputs = tmp_path / "downloads"
    inputs.mkdir()
    (inputs / "grid.raw").write_text(TOPOLOGY_CASE)
    projects = tmp_path / "projects"
    tools = ToolService(SessionContext.create(None, (), "fixture:model", "http://127.0.0.1:11434", projects_dir=projects))
    tools.create_project("Topology", [str(inputs / "grid.raw")])
    tools.configure_run({}, project="Topology")
    root = projects / "Topology"
    xml = (root / "original_inputs/input.xml").read_text()
    for run_id, case, xml_name in (("run_base", "grid.raw", "input.xml"), ("run_edited", "grid_sensitivity.raw", "input_sensitivity.xml")):
        work = root / "runs" / run_id / "work"
        work.mkdir(parents=True)
        (root / "runs" / run_id / "manifest.json").write_text(json.dumps({"xml_file": xml_name}))
        (root / "runs" / run_id / "status.json").write_text(json.dumps({"status": "completed"}))
        (work / xml_name).write_text(xml.replace("grid.raw", case))
    (root / "runs/run_base/work/grid.raw").write_text(TOPOLOGY_CASE)
    # The edited case takes the tie transformer out of service, splitting the network in two.
    (root / "runs/run_edited/work/grid_sensitivity.raw").write_text(TOPOLOGY_CASE.replace("'TIE XFMR    ',1,", "'TIE XFMR    ',0,"))
    (root / "runs/run_base/work/Topology_convergence.csv").write_text(
        "event_idx,contingency,type,converged,status_code\n"
        "1,BR_3_4_1 ,branch,false,ISLANDED\n"
        "2,BR_4_5_1 ,branch,true,OK\n"
        "3,BR_1_2_1 ,branch,true,OK\n"
        "4,BR_1_10_1 ,branch,false,ISLANDED\n"
    )
    return tools


def test_buses_and_elements_near_a_bus_or_a_branch(study):
    near = study.topology("buses_near", bus=4, hops=1, project="Topology")
    assert near["error"] is None
    rows = near["data"]["rows"]
    assert [(row["bus"], row["hops"]) for row in rows] == [(4, 0), (3, 1), (5, 1), (6, 1), (7, 1)]
    assert rows[3]["reached_by"] == "Transformer 4-6-7 circuit 1" and rows[0]["area"] == "2 SOUTH" and rows[0]["bus_name"] == "SOUTH HV"
    assert near["data"]["network"] == {"buses": 11, "elements": 11}
    assert any("isolated (type 4)" in warning for warning in near["warnings"])
    elements = study.topology("elements_near", bus=7, to_bus=9, hops=0, project="Topology")["data"]["rows"]
    assert [row["element"] for row in elements] == ["Branch 7 to 9 circuit 1"]
    around = study.topology("elements_near", bus=4, hops=1, project="Topology")["data"]["rows"]
    three = next(row for row in around if row["kind"] == "three-winding transformer")
    assert (three["element"], three["buses"], three["hops"]) == ("Transformer 4-6-7 circuit 1", [4, 6, 7], 1)


def test_path_steps_through_each_element_once(study):
    result = study.topology("path", bus=1, to_bus=9, project="Topology")["data"]
    assert result["elements_on_path"] == 5
    assert [(row["from_bus"], row["to_bus"], row["element"]) for row in result["rows"]] == [
        (1, 2, "Branch 1 to 2 circuit 1"), (2, 3, "Branch 2 to 3 circuit 1"), (3, 4, "Transformer 3 to 4 circuit 1"),
        (4, 7, "Transformer 4-6-7 circuit 1"), (7, 9, "Branch 7 to 9 circuit 1"),
    ]
    split = study.topology("path", bus=1, to_bus=9, run_id="run_edited", project="Topology")
    assert split["error"]["code"] == "NO_PATH"


def test_islands_of_a_run_read_its_own_case(study):
    """A sensitivity run is read from its edited case, not the project's."""
    base = study.topology("islands", run_id="run_base", project="Topology")["data"]
    edited = study.topology("islands", run_id="run_edited", project="Topology")
    assert base["island_count"] == 1 and edited["data"]["island_count"] == 2
    assert edited["data"]["case"].endswith("runs/run_edited/work/grid_sensitivity.raw")
    assert [(row["bus_count"], row["has_swing_bus"]) for row in edited["data"]["rows"]] == [(6, True), (5, False)]
    assert [row["island"] for row in study.topology("islands", run_id="run_edited", area="SOUTH", project="Topology")["data"]["rows"]] == [2]


def test_islanding_outages_carry_gridpacks_status(study):
    result = study.topology("islanding_outages", run_id="run_base", project="Topology")
    data = result["data"]
    rows = {row["outage"]: row for row in data["rows"]}
    tie = rows["Transformer 3 to 4 circuit 1"]
    assert (tie["gridpack_contingency"], tie["gridpack_status"], tie["cut_off_bus_count"], tie["cut_off_load_mw"], tie["remaining_has_swing_bus"]) == ("BR_3_4_1", "ISLANDED", 5, 10.0, True)
    assert rows["Branch 4 to 5 circuit 1"]["gridpack_status"] == "OK" and rows["Branch 7 to 9 circuit 1"]["gridpack_status"] is None
    assert (data["rows"][0]["outage"], data["order_by"], data["swing_bus_outages"]) == ("Transformer 3 to 4 circuit 1", "load_mw", [])
    # By default the outages that cut off the most load come first; bus_count orders them by what they cut off.
    loads = [row["cut_off_load_mw"] for row in data["rows"]]
    assert loads == sorted(loads, reverse=True)
    by_buses = study.topology("islanding_outages", order_by="bus_count", project="Topology")["data"]["rows"]
    assert [row["cut_off_bus_count"] for row in by_buses] == sorted((row["cut_off_bus_count"] for row in by_buses), reverse=True)
    assert data["gridpack_status_counts"] == {"ISLANDED": 1, "OK": 1, "not in this run": 4}
    # GridPACK called BR_1_10_1 islanded, but it splits nothing in the case, so the result says so.
    assert data["islanded_in_run_but_not_found"] == ["BR_1_10_1"] and any("split nothing" in warning for warning in result["warnings"])
    assert {source["path"].rsplit("/", 1)[-1] for source in result["provenance"]["sources"]} == {"manifest.json", "input.xml", "grid.raw", "Topology_convergence.csv"}
    north = study.topology("islanding_outages", area="1", project="Topology")["data"]["rows"]
    assert [row["outage"] for row in north] == ["Transformer 3 to 4 circuit 1"] and "gridpack_status" not in north[0]


@pytest.mark.parametrize(("arguments", "code"), [
    ({"query": "buses_near", "bus": 99}, "UNKNOWN_BUS"),
    ({"query": "buses_near", "bus": 8}, "ISOLATED_BUS"),
    ({"query": "buses_near"}, "MISSING_BUS"),
    ({"query": "path", "bus": 1}, "MISSING_BUS"),
    ({"query": "buses_near", "bus": 1, "hops": 21}, "INVALID_HOPS"),
    ({"query": "islands", "area": "EAST"}, "UNKNOWN_AREA"),
    ({"query": "islands", "run_id": "no_such_run"}, "RUN_NOT_FOUND"),
    ({"query": "islanding_outages", "order_by": "voltage"}, "INVALID_ORDER"),
])
def test_bad_topology_requests_are_refused(study, arguments, code):
    assert study.topology(project="Topology", **arguments)["error"]["code"] == code
