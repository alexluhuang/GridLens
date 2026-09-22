from __future__ import annotations

import csv
import json

import pytest

from gridlens.agent.session import SessionContext
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.parser_models import PARSER_VERSION


@pytest.fixture
def agent_project(tmp_path):
    root = tmp_path / "Synthetic_Project"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"name": "Synthetic Project"}))
    for run_id, offset in (("run_a", 0), ("run_b", 10)):
        run = root / "runs" / run_id
        work = run / "work"
        work.mkdir(parents=True)
        (run / "logs").mkdir()
        (run / "status.json").write_text('{"status": "completed"}')
        (run / "manifest.json").write_text(json.dumps({"run_id": run_id, "gridpack_image": "synthetic:test", "gridpack_executable": "ca.x", "mpi_processes": 4, "xml_file": "input.xml", "command": ["mpirun", "-n", "4", "ca.x", "input.xml"], "input_files": []}))
        (work / "input.xml").write_text("<Configuration><Contingency_analysis><FullBranchN1>true</FullBranchN1><minVoltage>0.9</minVoltage><maxVoltage>1.1</maxVoltage><contingencyRating>C</contingencyRating><qlim>true</qlim><qlimDeadband>0.1</qlimDeadband></Contingency_analysis><Powerflow><qlim>false</qlim><qlimDeadband>0.2</qlimDeadband></Powerflow></Configuration>")
        (work / "case.raw").write_text("Synthetic fixture only\n")
        (work / "case_flat.csv").write_text(
            "event_idx,contingency,from_bus,to_bus,circuit_id,section,rate_mva,loading_percent,viol\n"
            "0,base,1,2,1,,100,70,0\n"
            "1,line outage,1,2,1,,100,120,1\n"
            "2,island,1,2,1,2,100,90,0\n"
        )
        (work / "case_convergence.csv").write_text("event_idx,contingency,converged,status_code\n0,base,true,OK\n1,line outage,true,OK\n2,island,false,ISLANDED\n")
        rows = []
        for line_id, section, maximum, base, branch_type, kv in (
            ("1", "", 120, 70, "nontransformer_branch", 230),
            ("2", "", 80, 20, "nontransformer_branch", 230),
            ("1", "2", 110, 60, "nontransformer_branch", 230),
            ("T", "", 95, 60, "two_winding_transformer_branch", 115),
            ("L", "", 200, 90, "nontransformer_branch", 13.8),
        ):
            rows.append({"from_bus": 1, "to_bus": 2, "line_id": line_id, "section": section, "from_bus_name": "ALPHA", "to_bus_name": "BETA", "from_base_kv": kv, "to_base_kv": kv, "from_area": "1", "to_area": "2", "from_area_name": "North", "to_area_name": "South", "raw_branch_type": branch_type, "rate_mva": 100, "ratec": 100, "base_utilization_pct": base + offset, "mean_utilization_pct": 65, "max_utilization_pct": maximum + offset, "max_utilization_contingency": 1, "max_contingency_label": "line outage", "contingency_count": 3, "overload_count": int(maximum >= 100), "utilization_source": "csv_flat.loading_percent"})
        table_dir = run / "reports/interactive_tables"
        table_dir.mkdir(parents=True)
        tables = {"pflow_mm": rows, "branch_metadata": rows, "area_metadata": [{"area": 1, "area_name": "North"}, {"area": 2, "area_name": "South"}]}
        manifest = {"dataset_version": ANALYSIS_DATASET_VERSION, "parser_version": PARSER_VERSION, "tables": {}}
        for name, values in tables.items():
            path = table_dir / f"{name}.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(values[0]))
                writer.writeheader()
                writer.writerows(values)
            manifest["tables"][name] = {"source_file": "case.raw" if name == "area_metadata" else "case_flat.csv", "notes": [], "csv_path": str(path)}
        (run / "reports/interactive_analysis_manifest.json").write_text(json.dumps(manifest))
    return root


@pytest.fixture
def agent_context(agent_project):
    return SessionContext.create(agent_project, ("run_a", "run_b"), "fixture:model", "http://127.0.0.1:11434")
