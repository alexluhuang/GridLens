"""Compute the reference facts that answers to the planning-question evaluation are scored against.

It reads a projects folder that `prepare_agent_evaluation.py` made and writes one JSON object per question
ID. Totals by area, convergence counts, islanding outages, file sizes, and XML settings are read straight
from the files, independently of the agent tools, and so is question 23's interface flow, summed from the index
with PyArrow. Rankings, ties, cases, and comparisons come from the same
deterministic `rank` and `rank_groups` calls a model should make, run with every qualifier stated, so a
score compares a model's choices and wording with the tools' own answer. The script opens one session in
the prepared project, as the tools require, and does not change any run.

    python scripts/agent_question_references.py --projects-dir ~/GridLensProjects-eval --output references.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from gridlens.agent.session import SessionContext
from gridlens.agent.tools import ToolService
from gridlens.analysis.event_index import open_event_index
from gridlens.analysis.raw_sections import read_raw_sections

AREA_A, AREA_B, AREA_C = "Far West", "West", "North"
OUTAGE = "BR_190121_190104_1"
XML_SETTINGS = (
    "Contingency_analysis/contingencyRating", "Contingency_analysis/minVoltage", "Contingency_analysis/maxVoltage",
    "Contingency_analysis/FullBranchN1", "Contingency_analysis/FullGeneratorN1", "Contingency_analysis/qlim",
    "Contingency_analysis/qlimDeadband", "Contingency_analysis/LTC", "Powerflow/qlim", "Powerflow/qlimDeadband",
    "Powerflow/LTC", "Powerflow/networkConfiguration", "Powerflow/tolerance", "Powerflow/maxIteration",
)


def complete(result: dict) -> dict:
    """Return a tool result's data with every row, reading the saved copy of a result too large to send inline."""
    if result["error"]:
        return {"error": result["error"]}
    data = result["data"]
    if data.get("result_file"):
        data = json.loads(Path(data["result_file"]).read_text())["data"]
    return {**data, "warnings": result["warnings"]}


def brief(data: dict, fields: tuple[str, ...], limit: int = 25) -> dict:
    """Keep a ranking's counts and the named fields of its first rows."""
    counts = {key: data[key] for key in ("total_matching", "objects_in_scope", "excluded_by_filters", "excluded_unknown_value", "without_value", "excluded_not_converged", "only_in_run", "only_in_compare_run", "rating_changed_count", "rating_basis", "recorded_cases") if key in data}
    return {**counts, "rows": [{name: row.get(name) for name in fields if name in row} for row in data.get("rows", [])[:limit]], **({"error": data["error"]} if "error" in data else {})}


def files(run: Path) -> dict:
    """List a run's input, results, logs, and report files with their sizes in bytes."""
    listing = {}
    for folder in ("work", "logs", "reports/interactive_tables"):
        for path in sorted((run / folder).glob("*")) if (run / folder).is_dir() else ():
            if path.is_file():
                listing[str(path.relative_to(run))] = path.stat().st_size
    listing["reports/event_index"] = (run / "reports/event_index/manifest.json").is_file()
    listing["status"] = json.loads((run / "status.json").read_text())
    return listing


def xml_settings(path: Path) -> dict:
    """Read the named settings of a GridPACK XML file, each under its section."""
    root = ET.parse(path).getroot()
    found = {}
    for name in XML_SETTINGS:
        node = root.find(f".//{name}")
        found[name] = node.text.strip() if node is not None and node.text else None
    return found


def raw_totals(case: Path) -> dict:
    """Total in-service load by area, and generation by the area of each generator's bus, from a RAW case."""
    _, sections = read_raw_sections(case)
    section = {item.name: item for item in sections}
    names = {row["I"]: " ".join(str(row["ARNAME"]).split()) for row in section["AREA"].rows}
    bus_area = {row["I"]: row["AREA"] for row in section["BUS"].rows}
    load, generation, offline = defaultdict(float), defaultdict(float), Counter()
    for row in section["LOAD"].rows:
        if int(row["STATUS"]) == 1:
            load[names[row["AREA"]]] += float(row["PL"])
        else:
            offline["loads"] += 1
    for row in section["GENERATOR"].rows:
        if int(row["STAT"]) == 1:
            generation[names[bus_area[row["I"]]]] += float(row["PG"])
        else:
            offline["generators"] += 1
    rounded = lambda totals: {name: round(value, 1) for name, value in sorted(totals.items())}
    return {"load_mw": rounded(load), "generation_mw": rounded(generation), "out_of_service": dict(offline),
            "system_load_mw": round(sum(load.values()), 1), "system_generation_mw": round(sum(generation.values()), 1),
            "note": "The GENERATOR section has no AREA column; generation is summed by the area of each generator's bus."}


def interface_flow(run: Path, ties: list[dict], sending: str) -> dict:
    """Sum each case's real power across the ties, oriented out of the sending area, straight from the index.

    A tie whose from end is in the sending area adds its p_from_mw; one whose from end is in the other area
    subtracts it. Losses on the ties are ignored, as a simple interface sum does.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    sign = {f"{row['from_bus']}|{row['to_bus']}|{row['line_id']}|{row.get('section') or ''}": 1.0 if row["control_area"][0] == sending else -1.0 for row in ties}
    dataset, _, _ = open_event_index(run)
    keys = pa.array(sorted(sign), pa.string())
    parts = []
    for batch in dataset.scanner(columns=["event_idx", "contingency", "from_bus", "to_bus", "line_id", "section", "p_from_mw"], batch_size=262144).to_batches():
        table = pa.Table.from_batches([batch])
        key = pc.binary_join_element_wise(pc.cast(table["from_bus"], pa.string()), pc.cast(table["to_bus"], pa.string()), table["line_id"], table["section"], "|")
        mask = pc.is_in(key, value_set=keys)
        if pc.any(mask).as_py():
            parts.append(table.filter(mask).append_column("key", key.filter(mask)))
    table = pa.concat_tables(parts)
    table = table.append_column("oriented", pc.multiply(table["p_from_mw"], pa.array([sign[item] for item in table["key"].to_pylist()], pa.float64())))
    sums = table.group_by(["event_idx", "contingency"]).aggregate([("oriented", "sum")]).to_pylist()
    outages = [row for row in sums if row["event_idx"] != 0]
    low, high = min(outages, key=lambda row: row["oriented_sum"]), max(outages, key=lambda row: row["oriented_sum"])
    describe = lambda row: {"event_idx": row["event_idx"], "contingency": row["contingency"].strip(), "mw": round(row["oriented_sum"], 2)}
    return {"ties": len(sign), "sending_area": sending, "contingencies": len(outages),
            "base_case_mw": round(next(row["oriented_sum"] for row in sums if row["event_idx"] == 0), 2),
            "minimum": describe(low), "maximum": describe(high)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--projects-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    runs = json.loads((args.projects_dir.expanduser() / "eval_runs.json").read_text())
    project = Path(runs["project"])
    a, b = runs["run_a"], runs["run_b"]
    run_a = project / "runs" / a
    tools = ToolService(SessionContext.create(project, (a, b), "references", "http://127.0.0.1:11434", projects_dir=args.projects_dir.expanduser()))
    ties = [{"column": "control_area", "op": "==", "value": AREA_A}, {"column": "control_area", "op": "==", "value": AREA_B}]
    facility = ("object", "from_bus", "to_bus", "line_id", "value", "control_area", "nominal_kv", "rating_mva", "base_utilization_pct", "max_utilization_pct", "compare_value", "binding_contingency", "branch_type")
    case = ("event_idx", "contingency", "object", "value", "p_from_mw", "q_from_mvar", "mva_from", "rate_mva", "v_from_pu", "v_to_pu", "ang_from_deg", "ang_to_deg", "converged", "outage_area")
    outage = ("event_idx", "contingency", "value", "max_loading_pct", "overload_count", "type", "outage_area")
    reference: dict[str, object] = {}

    reference["1"] = [{key: row.get(key) for key in ("run_id", "status", "analysis_current", "event_index_available")} for row in complete(tools.get_project())["rows"]]
    reference["2a"] = files(run_a)
    reference["2b"] = files(project / "runs" / runs["run_d"])
    reference["3"] = xml_settings(run_a / "work/input.xml")
    manifests = complete(tools.read_file(str(run_a / "manifest.json"), compare_path=str(project / "runs" / b / "manifest.json"), limit=0))
    configurations = complete(tools.read_file(str(run_a / "work/input.xml"), compare_path=str(project / "runs" / b / "work/input.xml"), limit=0))
    reference["4"] = {"manifest": manifests["rows"], "input_xml": configurations["rows"]}
    reference["5"] = raw_totals(run_a / "work/Texas7k_20210804.raw")
    _, sections = read_raw_sections(run_a / "work/Texas7k_20210804.raw")
    reference["6"] = [{key: row[key] for key in ("I", "NAME", "BASKV", "AREA", "ZONE")} for row in next(item for item in sections if item.name == "BUS").rows if "BERNA" in str(row["NAME"]).upper()]
    with (run_a / "work/GridPACK_Test_Project_convergence.csv").open(newline="") as handle:
        convergence = list(csv.DictReader(handle))
    statuses = Counter(" ".join(row["status_code"].split()) for row in convergence)
    reference["7"] = {"recorded": len(convergence), "status_code": {name: statuses.get(name, 0) for name in ("OK", "DIVERGED", "ISLANDED", "NO_SLACK", "SLACK_OVERLOAD")}, "converged_column_true": sum(row["converged"].strip() == "true" for row in convergence)}
    islanded = [row for row in convergence if row["status_code"].strip() == "ISLANDED"]
    reference["8"] = {"count": len(islanded), "by_type": dict(Counter(row["type"].strip() for row in islanded)), "first": [row["contingency"].strip() for row in islanded[:10]]}
    reference["9"] = {"branches": brief(complete(tools.rank(a, magnitude=20, fields=["control_area", "nominal_kv", "rating_mva", "binding_contingency"])), facility, 20),
                      "both": brief(complete(tools.rank(a, object="both", magnitude=5, fields=["branch_type"])), facility, 5)}
    reference["10"] = brief(complete(tools.rank(a, metric="overload_count", magnitude=10, fields=["max_utilization_pct"])), facility, 10)
    coast_345 = [{"column": "nominal_kv", "op": ">=", "value": 345}, {"column": "control_area", "op": "==", "value": "Coast"}]
    reference["11"] = brief(complete(tools.rank(a, metric="thermal_margin_pct_points", magnitude=10, filters=coast_345, fields=["max_utilization_pct", "nominal_kv"])), facility, 10)
    waller = [{"column": "bus_name", "op": "matches", "value": "WALLER 1 1"}, {"column": "bus_name", "op": "matches", "value": "NAVASOTA 2 1"}]
    reference["12"] = brief(complete(tools.rank(a, object="both", filters=waller, fields=["base_utilization_pct", "rating_mva", "nominal_kv"])), facility, 2)
    reference["13"] = brief(complete(tools.rank(a, object="both", magnitude=0, filters=ties, fields=["base_utilization_pct", "control_area", "branch_type"])), facility, 30)
    reference["14"] = {"worst_by_outage_area": brief(complete(tools.rank_groups(a, object="cases", group="outage_area", metric="loading_percent", statistic="max", magnitude=0, filters=ties)), ("group", "value", "count")),
                       "worst_in_area_c": brief(complete(tools.rank(a, object="cases", magnitude=3, filters=ties + [{"column": "outage_area", "op": "==", "value": AREA_C}], fields=["outage_area"])), case, 3)}
    reference["15"] = {"by_loading": brief(complete(tools.rank(a, object="contingencies", metric="max_loading_pct", magnitude=10, fields=["overload_count", "outage_area"])), outage, 10),
                       "by_overloads": brief(complete(tools.rank(a, object="contingencies", metric="overload_count", magnitude=10, fields=["max_loading_pct", "outage_area"])), outage, 10)}
    reference["16"] = {"contingency": brief(complete(tools.rank(a, object="contingencies", filters=[{"column": "contingency", "op": "==", "value": OUTAGE}], fields=["overload_count", "converged"])), outage, 1),
                       "overloads": brief(complete(tools.rank(a, object="cases", magnitude=0, filters=[{"column": "contingency", "op": "==", "value": OUTAGE}, {"column": "loading_percent", "op": ">=", "value": 100}], fields=["p_from_mw", "q_from_mvar", "mva_from", "rate_mva"])), case, 10),
                       # The summary also counts rows GridPACK flags with viol, such as the outaged branch itself at 0%.
                       "flagged": brief(complete(tools.rank(a, object="cases", magnitude=0, filters=[{"column": "contingency", "op": "==", "value": OUTAGE}, {"column": "viol", "op": "==", "value": 1}], fields=["viol"])), case, 10)}
    low = [{"column": "min_voltage_pu", "op": "<", "value": 0.95}]
    reference["17"] = {"lowest": brief(complete(tools.rank(a, object="cases", metric="min_voltage_pu", order="ascending", magnitude=10, filters=low, fields=["v_from_pu", "v_to_pu", "converged"])), case, 10),
                       "by_contingency": brief(complete(tools.rank_groups(a, object="cases", group="contingency", metric="min_voltage_pu", statistic="count", magnitude=10, filters=low)), ("group", "value"), 10)}
    reference["18"] = brief(complete(tools.rank(a, object="cases", metric="angle_difference_deg", magnitude=5, filters=ties + [{"column": "event_idx", "op": ">", "value": 0}], fields=["ang_from_deg", "ang_to_deg", "converged"])), case, 5)
    reference["23"] = interface_flow(run_a, reference["13"]["rows"], AREA_A)
    reference["19"] = brief(complete(tools.rank(a, object="both", compare_run_id=b, magnitude=10, fields=["compare_value", "max_utilization_pct", "control_area"])), facility, 10)
    new = [{"column": "max_utilization_pct", "op": "<", "value": 100}, {"column": "compare_value", "op": ">=", "value": 100}]
    resolved = [{"column": "max_utilization_pct", "op": ">=", "value": 100}, {"column": "compare_value", "op": "<", "value": 100}]
    reference["20"] = {"new": brief(complete(tools.rank(a, object="both", compare_run_id=b, magnitude=0, filters=new, fields=["compare_value", "max_utilization_pct"])), facility, 30),
                       "resolved": brief(complete(tools.rank(a, object="both", compare_run_id=b, magnitude=0, order="ascending", filters=resolved, fields=["compare_value", "max_utilization_pct"])), facility, 30)}
    key = lambda f, t: [{"column": "from_bus", "op": "==", "value": f}, {"column": "to_bus", "op": "==", "value": t}]
    reference["30a"] = brief(complete(tools.rank(a, object="both", filters=key(110045, 110119))), facility)
    branches = next(item for item in sections if item.name == "BRANCH").rows
    reference["30b"] = {"results": brief(complete(tools.rank(a, object="both", filters=key(110045, 110118), fields=["base_utilization_pct", "rating_mva"])), facility),
                        "raw_circuits": [{key_: row[key_] for key_ in ("I", "J", "CKT", "RATEA", "RATEC", "ST")} for row in branches if {row["I"], abs(row["J"])} == {110045, 110118}]}
    args.output.write_text(json.dumps(reference, indent=1, default=str))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
