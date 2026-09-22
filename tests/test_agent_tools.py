from __future__ import annotations

import json
import os

import pytest

from gridlens.agent.session import SessionContext
from gridlens.agent.tools import MAX_RESULT_BYTES, ToolService
from gridlens.analysis.interactive import _load_cached_interactive_dataset
from gridlens.analysis.loading import max_line_utilization_rows


def test_ranking_matches_gui_and_keeps_circuits_sections(agent_context):
    service = ToolService(agent_context)
    result = service.rank_branch_loading("run_a", limit=2)
    assert result["error"] is None
    assert result["data"]["total_matching"] == 3
    assert result["data"]["truncated"] is True
    assert [row["max_utilization_pct"] for row in result["data"]["rows"]] == [120, 110]
    assert [row["section"] for row in result["data"]["rows"]] == ["", "2"]
    gui = max_line_utilization_rows(_load_cached_interactive_dataset(agent_context.run("run_a")).tables)
    assert sorted(row["max_utilization_pct"] for row in gui) == [80, 110, 120]
    assert result["data"]["convergence"] == {"known": True, "total": 3, "converged": 2, "failed": 1}
    assert any("not a converged N-1-only" in warning for warning in result["warnings"])
    assert result["provenance"]["sources"]
    assert all(not source["path"].startswith("/") for source in result["provenance"]["sources"])


def test_margin_base_transformers_groups_and_threshold(agent_context):
    service = ToolService(agent_context)
    margin = service.rank_branch_loading("run_a", metric="thermal_margin_pct_points")
    assert [row["thermal_margin_pct_points"] for row in margin["data"]["rows"]] == [20, -10, -20]
    base = service.rank_branch_loading("run_a", metric="base_utilization_pct")
    assert base["data"]["rows"][0]["base_utilization_pct"] == 70
    transformer = service.rank_branch_loading("run_a", facility="two_winding_transformer")
    assert transformer["data"]["rows"][0]["line_id"] == "T"
    assert service.list_thermal_violations("run_a", threshold_pct=110)["data"]["total_matching"] == 1
    grouped = service.summarize_loading("run_a", group_by="area")
    assert [row["line_count"] for row in grouped["data"]["rows"]] == [3, 3]
    assert grouped["data"]["rows"][0]["average_utilization_pct"] == pytest.approx(103.333333)


def test_branch_search_method_and_comparison(agent_context):
    service = ToolService(agent_context)
    assert service.get_branch_loading("run_a", 1, 2, "1", "2")["data"]["rows"][0]["max_utilization_pct"] == 110
    assert service.search_buses("run_a", "al")["data"]["rows"][0]["bus_id"] == "1"
    assert service.get_run_method("run_a")["data"]["rows"][0]["xml_settings"]["FullBranchN1"] == "true"
    comparison = service.compare_runs("run_a", "run_b")
    assert all(row["delta_pct_points"] == 10 for row in comparison["data"]["rows"])
    assert comparison["data"]["first_only"] == comparison["data"]["second_only"] == 0
    assert len(service.get_run_inventory()["data"]["rows"]) == 2


@pytest.mark.parametrize("run_id", ["../run_b", "/tmp", "unselected", "run_a/../../run_b"])
def test_run_scope_rejects_paths(agent_context, run_id):
    result = ToolService(agent_context).rank_branch_loading(run_id)
    assert result["error"]["code"] == "RUN_NOT_SELECTED"


def test_unselected_completed_run_is_inaccessible(agent_project):
    context = SessionContext.create(agent_project, ("run_a",), "fixture:model", "http://127.0.0.1:11434")
    assert ToolService(context).compare_runs("run_a", "run_b")["error"]["code"] == "RUN_NOT_SELECTED"


def test_stale_cache_never_reads_flat_data(agent_context, monkeypatch):
    source = agent_context.run("run_a") / "work/case_flat.csv"
    os.utime(source, (2_000_000_000, 2_000_000_000))
    import gridlens.analysis.dataset as dataset
    monkeypatch.setattr(dataset, "build_run_analysis", lambda *a, **k: pytest.fail("cold parse must not run"))
    assert ToolService(agent_context).rank_branch_loading("run_a")["error"]["code"] == "ANALYSIS_NOT_BUILT"


def test_symlink_escape_blocked(agent_context, tmp_path):
    cache = agent_context.run("run_a") / "reports/interactive_tables/pflow_mm.csv"
    target = tmp_path / "outside.csv"
    cache.rename(target)
    cache.symlink_to(target)
    assert ToolService(agent_context).rank_branch_loading("run_a")["error"]["code"] == "PATH_OUTSIDE_SESSION"


def test_source_path_in_manifest_cannot_escape(agent_context):
    manifest = agent_context.run("run_a") / "reports/interactive_analysis_manifest.json"
    data = json.loads(manifest.read_text())
    data["tables"]["pflow_mm"]["source_file"] = "../../run_b/work/case_flat.csv"
    manifest.write_text(json.dumps(data))
    assert ToolService(agent_context).rank_branch_loading("run_a")["error"]["code"] == "PATH_OUTSIDE_SESSION"


def test_invalid_filters_and_result_caps_are_audited(agent_context):
    service = ToolService(agent_context)
    assert service.rank_branch_loading("run_a", min_kv=0)["error"]["code"] == "INVALID_FILTER"
    result = service.rank_branch_loading("run_a", limit=10_000)
    assert result["data"]["returned"] <= 50
    assert len(json.dumps(result).encode()) < MAX_RESULT_BYTES
    records = [json.loads(line) for line in (agent_context.directory / "tool_calls.jsonl").read_text().splitlines()]
    completed = [record for record in records if record["phase"] == "completed"]
    assert [record["call_id"] for record in completed] == ["T1", "T2"]
    assert completed[0]["outcome"] == "error"
    assert completed[1]["result"] == result


def test_session_roundtrip_and_tampered_directory(agent_context):
    path = agent_context.directory / "context.json"
    assert SessionContext.load(path) == agent_context
    data = json.loads(path.read_text())
    data["directory"] = "/tmp"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="session context is invalid"):
        SessionContext.load(path)
