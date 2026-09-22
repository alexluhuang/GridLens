from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from gridlens.agent.controller import AgentController, audited_row_scope_answer, cite_uncited_turn, disclose_tool_failures, disclose_truncated_results, group_mean_request, normalize_citations, qualify_capacity_answer, session_sources, top_line_area_request, verified_group_mean_answer, verified_singular_line_area, verified_top_line_areas
from gridlens.agent.hermes import HermesAdapter
from gridlens.agent.policy import AgentError, local_endpoint, verify_model
from gridlens.agent.process import mcp_command, minimal_environment
from gridlens.agent.prompt import SYSTEM_PROMPT
from gridlens.agent.runtime import PreparedRuntime, RuntimeStatus
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import ToolService


@pytest.mark.parametrize("url", ["https://example.com", "http://192.168.1.2:11434", "http://user:pass@127.0.0.1:11434", "file:///tmp/model", "http://127.0.0.1:11434/proxy", "http://127.0.0.1:11434?url=remote"])
def test_policy_rejects_nonlocal_or_ambiguous_routes(url):
    with pytest.raises(AgentError):
        local_endpoint(url)


def test_policy_pins_loopback_and_rejects_mixed_dns(monkeypatch):
    assert local_endpoint("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"
    import gridlens.agent.policy as policy
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 11434)), (0, 0, 0, "", ("10.0.0.1", 11434))])
    with pytest.raises(AgentError):
        local_endpoint("http://localhost:11434")


def test_cloud_models_and_models_without_tools_are_rejected(monkeypatch):
    import gridlens.agent.policy as policy
    monkeypatch.setattr(policy, "ollama_json", lambda *a: {"capabilities": ["tools"], "remote_host": "https://remote.invalid"})
    with pytest.raises(AgentError, match="cloud"):
        verify_model("http://127.0.0.1:11434", "anything")
    monkeypatch.setattr(policy, "ollama_json", lambda *a: {"capabilities": ["completion"]})
    with pytest.raises(AgentError, match="tool calls"):
        verify_model("http://127.0.0.1:11434", "anything")


def test_preparation_isolated_profile_and_no_inherited_credentials(agent_context, monkeypatch):
    import gridlens.agent.hermes as hermes
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret")
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://remote.invalid")
    adapter = HermesAdapter()
    monkeypatch.setattr(adapter, "probe", lambda: RuntimeStatus(True, "ok", "/opt/hermes", "0.21.4", agent_context.endpoint, (agent_context.model,)))
    monkeypatch.setattr(hermes, "verify_model", lambda *a: None)
    prepared = adapter.prepare(agent_context)
    assert "HTTP_PROXY" not in prepared.environment
    assert "ANTHROPIC_API_KEY" not in prepared.environment
    assert "test-secret" not in json.dumps(prepared.environment)
    assert prepared.environment["CUSTOM_BASE_URL"] == agent_context.endpoint + "/v1"
    assert Path(prepared.environment["HERMES_HOME"]).is_relative_to(agent_context.directory)
    assert prepared.cwd != agent_context.project_root
    config = json.loads((Path(prepared.environment["HERMES_HOME"]) / "config.yaml").read_text())
    assert config["toolsets"] == ["gridlens"]
    assert list(config["mcp_servers"]) == ["gridlens"]
    assert config["auth"]["adopt_external_logins"] is False
    assert config["agent"]["system_prompt"] == SYSTEM_PROMPT
    # Pin the exact argv: dropping --ignore-rules or --toolsets gridlens would otherwise leave the suite green.
    assert prepared.command == (
        "/opt/hermes", "chat", "--oneshot", "--format", "stream-json", "--provider", "custom",
        "--model", agent_context.model, "--toolsets", "gridlens", "--ignore-rules", "--no-restore-cwd",
        "--max-turns", "12", "--run-budget", "300", "--source", "tool", "--cli",
    )
    manifest = json.loads((agent_context.directory / "manifest.json").read_text())
    # Literals, not hermes.TURN_TIMEOUT_SECONDS, so a silent budget or turn-cap change is caught here.
    assert manifest["command_template"] == list(prepared.command) + ["--query-file", "<session prompt file>"]
    assert manifest["route"] == "loopback_only"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert mcp_command() == [sys.executable, "--mcp-server"]


def test_start_turn_passes_prompt_by_file_and_validates_continuation(agent_context, monkeypatch, tmp_path):
    import gridlens.agent.hermes as hermes
    adapter = HermesAdapter()
    monkeypatch.setattr(hermes, "verify_model", lambda *a: None)
    prepared = PreparedRuntime(agent_context, ("/opt/hermes", "chat", "--oneshot"), {"PATH": os.environ["PATH"]}, tmp_path)
    calls = []

    class FakePopen:
        # Local so the offline suite never spawns the real CLI, while still capturing the full invocation.
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))

    monkeypatch.setattr(hermes.subprocess, "Popen", FakePopen)
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("literal $(touch /tmp/should-never-exist) `id` secret-text")
    adapter.start_turn(prepared, prompt_path, "abc-1")
    argv, kwargs = calls[0]
    assert argv == [*prepared.command, "--query-file", str(prompt_path), "--resume", "abc-1"]
    assert all("secret-text" not in part for part in argv)
    assert kwargs["cwd"] == prepared.cwd and kwargs["cwd"] != agent_context.project_root
    assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["start_new_session"] is True
    assert kwargs["env"] == prepared.environment
    # "аbc" is a Cyrillic look-alike: it catches a later relaxation of the class to Unicode-aware \w.
    for bad in ("--toolsets all", "a b", "$(id)", "x;y", "../../other", "abc\n--resume", "аbc"):
        calls.clear()
        with pytest.raises(AgentError) as caught:
            adapter.start_turn(prepared, prompt_path, bad)
        assert caught.value.code == "INVALID_CONTINUATION"
        assert not calls


def test_structured_events_and_unexpected_tool():
    adapter = HermesAdapter()
    assert adapter.parse_event('{"type":"text","text":" hello"}').text == " hello"
    result = adapter.parse_event('{"type":"result","exit_code":0,"text":"Done [T1]","tokens":{"total":10},"session_id":"abc"}')
    assert result.kind == "completed"
    assert result.data["usage"] == {"total": 10}
    with pytest.raises(AgentError, match="non-GridLens"):
        adapter.parse_event('{"type":"tool_use","name":"terminal"}')
    with pytest.raises(AgentError):
        adapter.parse_event("unexpected banner")


@pytest.mark.parametrize("citation", ["[T1]", "[Call\u202fT1]", "[\u200bT1]", "(call_id\u202fT1)", "call_id: t1"])
def test_explicit_citations_resolve_only_known_audit_ids(citation):
    assert normalize_citations(citation, [{"call_id": "T1"}]) == "[T1]"
    assert normalize_citations(citation, []) == "[T1: invalid source]"


def test_uncited_model_answer_reports_only_current_successful_sources():
    """A model's missing citation is visible, with no failed or older calls implied as support."""
    sources = [{"call_id": "T2", "outcome": "ok"}]
    assert cite_uncited_turn("120%", sources) == "120%\n\nSources consulted (model omitted inline citations): [T2]"
    assert cite_uncited_turn("120% [T2]", sources) == "120% [T2]"
    assert cite_uncited_turn("No data", []) == "No data"
    assert cite_uncited_turn("No data", [{"call_id": "T2", "outcome": "error"}]) == "No data"
    note = disclose_truncated_results("120%", [{"call_id": "T2", "result": {"data": {"truncated": True, "returned": 10, "total_matching": 6823}}}])
    assert "[T2] returned 10 of 6,823 matching rows" in note
    assert "Omitted rows were not supplied to the model" in note
    assert disclose_truncated_results("No data", []) == "No data"
    assert "Build / refresh analysis" in disclose_tool_failures("No lines", [{"call_id": "T2", "result": {"error": {"code": "ANALYSIS_NOT_BUILT"}}}])
    capped = [{"call_id": "T2", "outcome": "error", "result": {"error": {"code": "LIMIT_EXCEEDS_CAP"}, "data": {"max_rows_per_call": 50}}}]
    assert disclose_tool_failures("All 6,823 rows returned", capped) == "GridLens rejected [T2]: the requested limit exceeds 50 rows per call. No rows were returned. Use summarize_loading for full-run averages."
    assert qualify_capacity_answer("20 percentage points", "How much extra capacity?").endswith("requires a separate power-flow study.")


def test_group_mean_answer_requires_complete_audited_summary(agent_context):
    """Use a scoped fixture to reject ranked-row averages and format all-row voltage means."""
    service = ToolService(agent_context)
    question = "Rank all voltage categories by mean max utilization."
    service.rank_branch_loading("run_a", limit=1)
    ranked_only = verified_group_mean_answer("The mean is 120%", question, session_sources(agent_context.directory), ("run_a",))
    assert "1 of 3 facilities" in ranked_only
    assert "120%" not in ranked_only
    service.summarize_loading("run_a", group_by="voltage")
    complete = verified_group_mean_answer("The mean is 120%", question, session_sources(agent_context.directory), ("run_a",))
    assert "across all 3 matching facilities" in complete
    assert "230-344 kV: 103.3%" in complete
    assert "The mean is 120%" not in complete
    assert "[T2]" in complete


def test_group_mean_scope_does_not_substitute_all_areas_for_filters():
    """Leave area- and cutoff-filtered means to explicit tool calls instead of an all-area fallback."""
    assert group_mean_request("Mean line utilization by voltage group in run_a") == ("voltage", "line")
    assert group_mean_request("Mean line utilization by voltage group for lines at least 50 kV") == ("voltage", "line")
    assert group_mean_request("Mean line utilization by voltage group in East") is None
    assert group_mean_request("Mean line utilization by voltage group for area East") is None
    assert group_mean_request("Mean line utilization by voltage group above 230 kV") is None


def test_controller_repairs_wrong_facility_scope_for_group_means(agent_context, monkeypatch):
    """Check that a model's all-facility summary is replaced by a line-only audited summary."""
    context = SessionContext.create(agent_context.project_root, ("run_a",), "fixture:model", agent_context.endpoint)
    adapter = StubAdapter('print(\'{"type":"result","exit_code":0,"text":"The mean is 95%"}\')')
    controller = AgentController(context, adapter)

    def model_answer(process, emit, buffers):
        # Simulate a model using the right summary tool with the wrong facility filter.
        ToolService(context).summarize_loading("run_a", group_by="voltage", facility="all")
        process.wait(timeout=2)
        return "The mean is 95%", 0

    monkeypatch.setattr(controller, "_consume_output", model_answer)
    answer = controller.run_turn("Rank all voltage groups by mean maximum observed line utilization.", lambda event: None)
    summaries = [row for row in session_sources(context.directory) if row["tool"] == "summarize_loading"]
    assert [row["arguments"]["facility"] for row in summaries] == ["all", "line"]
    assert "across all 3 matching facilities" in answer
    assert "230-344 kV: 103.3%" in answer
    assert "95%" not in answer
    assert "[T2]" in answer


def test_row_scope_questions_use_audited_counts_and_refusals(agent_context):
    """Read real fixture tool audits to correct model claims about rows, caps, and group populations."""
    service = ToolService(agent_context)
    service.rank_branch_loading("run_a", limit=1)
    first = audited_row_scope_answer("All rows were returned", "How many rows were displayed?", session_sources(agent_context.directory))
    assert "[T1] returned 1 of 3 matching facility rows; truncated: True" in first
    assert "All rows were returned" not in first
    service.rank_branch_loading("run_a", limit=7000)
    second = audited_row_scope_answer("All rows were returned", "Did T2 return 7,000 rows?", session_sources(agent_context.directory))
    assert "[T2] returned no rows because the call failed with LIMIT_EXCEEDS_CAP" in second
    assert "Requested row limit: 7,000; maximum permitted per call: 50" in second
    service.summarize_loading("run_a", group_by="voltage")
    third = audited_row_scope_answer("The average used one row", "How many rows were used for T3?", session_sources(agent_context.directory))
    assert "[T3] returned 1 of 1 matching category rows" in third
    assert "all 3 matching facilities" in third


def test_top_line_areas_and_singular_followup_use_audited_endpoint_labels(agent_context):
    """Check top-line area answers against the ranked rows instead of model-generated names."""
    assert top_line_area_request("List the areas for the top 5 most congested lines.") == 5
    assert top_line_area_request("List the areas for the top 5 most congested lines in East.") is None
    ToolService(agent_context).rank_branch_loading("run_a", limit=3)
    sources = session_sources(agent_context.directory)
    answer = verified_top_line_areas("East, East", "List the areas for the top 2 most congested lines.", sources, ("run_a",))
    assert "North, South (120.0%)" in answer
    assert "North, South (110.0%)" in answer
    assert "East" not in answer
    followup = verified_singular_line_area("East", "What control area is that line in?", "The most congested line is ALPHA to BETA (1).", sources, ("run_a",))
    assert "North, South [T1]" in followup


class StubAdapter(HermesAdapter):
    def __init__(self, script: str) -> None:
        self.script = script

    def prepare(self, session):
        return PreparedRuntime(session, (), minimal_environment(), session.directory)

    def start_turn(self, prepared, prompt_path, continuation=""):
        return subprocess.Popen([sys.executable, "-u", "-c", self.script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)


def test_controller_records_prompt_and_answer_without_shell(agent_context):
    adapter = StubAdapter('print(\'{"type":"result","exit_code":0,"text":"done [T1]","session_id":"abc","tokens":{"total":1}}\')')
    controller = AgentController(agent_context, adapter)
    events = []
    prompt = "literal $(touch /tmp/should-never-exist) `command` 'quoted'"
    assert controller.run_turn(prompt, events.append) == "done [T1: invalid source]"
    transcript = [json.loads(line) for line in (agent_context.directory / "transcript.jsonl").read_text().splitlines()]
    assert transcript[0]["text"] == prompt
    assert transcript[1]["text"] == "done [T1: invalid source]"
    assert controller.continuation == "abc"
    assert json.loads((agent_context.directory / "status.json").read_text())["status"] == "completed"


def test_controller_fetches_top_line_areas_when_model_omits_ranking(agent_context):
    """Check run_turn adds an audited ranking and replaces an unsupported area list."""
    context = SessionContext.create(agent_context.project_root, ("run_a",), "fixture:model", agent_context.endpoint)
    adapter = StubAdapter('print(\'{"type":"result","exit_code":0,"text":"East, East, East"}\')')
    answer = AgentController(context, adapter).run_turn("List the areas for the top 5 most congested lines.", lambda event: None)
    assert "Top 3 congested lines" in answer
    assert answer.count("North, South") == 3
    assert "East" not in answer
    assert "Only 3 eligible lines" in answer
    assert session_sources(context.directory)[0]["tool"] == "rank_branch_loading"


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_stop_reap_child_processes(agent_context, cancel):
    pid_file = agent_context.directory / "child.pid"
    script = "import subprocess, sys, time; from pathlib import Path; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); Path(" + repr(str(pid_file)) + ").write_text(str(p.pid)); time.sleep(120)"
    controller = AgentController(agent_context, StubAdapter(script), timeout=0.5 if not cancel else 5)
    timer = threading.Timer(0.5, controller.cancel) if cancel else None
    if timer:
        timer.start()
    try:
        with pytest.raises(AgentError) as caught:
            controller.run_turn("hello", lambda event: None)
        assert caught.value.code == ("CANCELLED" if cancel else "TIMEOUT")
        child = int(pid_file.read_text())
        for _ in range(50):
            stat = Path(f"/proc/{child}/stat")
            try:
                state = stat.read_text().split()[2]
            except (FileNotFoundError, ProcessLookupError):
                break
            if state == "Z":
                break
            time.sleep(0.02)
        else:
            pytest.fail("Agent child process survived Stop/timeout")
    finally:
        if timer:
            timer.cancel()
