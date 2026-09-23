"""The provider seam: one contract, three runtimes, no model-specific code above the adapter."""
from __future__ import annotations

import json

import pytest

from gridlens.agent.claude_code import ALLOWED_TOOLS, ClaudeCodeAdapter
from gridlens.agent.codex import CodexAdapter
from gridlens.agent.policy import AgentError, HOSTED_GATE_ENV, hosted_authorization, require_hosted_authorization
from gridlens.agent.prompt import MAX_REPLAY_CHARS, SYSTEM_PROMPT, session_facts, turn_prompt
from gridlens.agent.providers import DESCRIPTORS, PROVIDER_IDS, create_adapter, descriptor, route_for
from gridlens.agent.runtime import RuntimeStatus
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import TOOL_NAMES


def test_every_descriptor_builds_an_adapter_that_satisfies_the_contract():
    assert PROVIDER_IDS == {"hermes", "claude", "codex"}
    for item in DESCRIPTORS:
        adapter = create_adapter(item.provider)
        assert adapter.provider == item.provider
        assert adapter.route == item.route == route_for(item.provider)
        for member in ("probe", "prepare", "start_turn", "parse_event", "cancel"):
            assert callable(getattr(adapter, member))
        assert isinstance(adapter.supports_continuation, bool)
    with pytest.raises(AgentError, match="supports"):
        descriptor("some-other-model")


def test_prompt_and_tool_surface_name_no_provider_or_model():
    lowered = SYSTEM_PROMPT.lower()
    for name in ("hermes", "ollama", "codex", "claude", "nemotron", "llama", "qwen", "gemma", "granite", "gpt-oss", "openai", "anthropic"):
        assert name not in lowered, name
    # Every runtime offers the identical catalog; the tool layer has no provider branch.
    assert set(ALLOWED_TOOLS) == {f"mcp__gridlens__{name}" for name in TOOL_NAMES}


def test_hosted_runtimes_stay_closed_without_written_authorization(monkeypatch):
    monkeypatch.delenv(HOSTED_GATE_ENV, raising=False)
    assert hosted_authorization() == ""
    for provider in ("claude", "codex"):
        with pytest.raises(AgentError) as error:
            require_hosted_authorization(provider)
        assert error.value.code == "HOSTED_DISABLED"
        assert "governance" in str(error.value)
    monkeypatch.setenv(HOSTED_GATE_ENV, "1")
    require_hosted_authorization("claude", isolation_proven=True)
    with pytest.raises(AgentError, match="cannot prove"):
        require_hosted_authorization("codex", isolation_proven=False)


def test_remote_session_records_its_route_and_needs_an_acknowledgement(agent_project, monkeypatch):
    monkeypatch.setenv(HOSTED_GATE_ENV, "1")
    with pytest.raises(AgentError) as error:
        SessionContext.create(agent_project, ("run_a",), "default", "", runtime="claude")
    assert error.value.code == "REMOTE_NOT_ACKNOWLEDGED"
    context = SessionContext.create(agent_project, ("run_a",), "default", "", runtime="claude", remote_acknowledged=True)
    assert (context.route, context.endpoint, context.remote_acknowledged) == ("remote", "", True)
    reloaded = SessionContext.load(context.directory / "context.json")
    assert reloaded == context
    # A local session keeps its loopback endpoint and never claims an acknowledgement it did not get.
    local = SessionContext.create(agent_project, ("run_a",), "fixture:model", "http://127.0.0.1:11434")
    assert (local.route, local.runtime, local.remote_acknowledged) == ("loopback_only", "hermes", False)


def test_codex_fails_closed_and_records_why(agent_project, monkeypatch):
    monkeypatch.setenv(HOSTED_GATE_ENV, "1")
    context = SessionContext.create(agent_project, ("run_a",), "default", "", runtime="codex", remote_acknowledged=True)
    adapter = CodexAdapter()
    with pytest.raises(AgentError) as error:
        adapter.prepare(context)
    assert error.value.code in ("ISOLATION_UNPROVEN", "RUNTIME_UNAVAILABLE")
    assert not (context.directory / "manifest.json").exists()
    argv = adapter.session_argv(context, "/usr/bin/codex")
    for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "--json"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert not any("dangerously" in item for item in argv)
    assert "shell_tool" in argv and "unified_exec" in argv
    assert any(item.startswith("mcp_servers.gridlens.command=") for item in argv)
    assert not any(str(agent_project / "runs") in item for item in argv)


def test_claude_session_exposes_only_gridlens_tools(agent_project, monkeypatch):
    monkeypatch.setenv(HOSTED_GATE_ENV, "1")
    context = SessionContext.create(agent_project, ("run_a",), "default", "", runtime="claude", remote_acknowledged=True)
    adapter = ClaudeCodeAdapter()
    monkeypatch.setattr(adapter, "probe", lambda: RuntimeStatus(
        True, "stub", "/usr/bin/claude", "2.1.278", "", ("default",),
        provider="claude", route="remote", authenticated=True,
    ))
    prepared = adapter.prepare(context)
    argv = list(prepared.command)
    for flag in ("--print", "--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert not any("dangerously" in item for item in argv)
    assert not any("bypassPermissions" in item for item in argv)
    allowed = argv[argv.index("--allowedTools") + 1: argv.index("--allowedTools") + 1 + len(TOOL_NAMES)]
    assert set(allowed) == set(ALLOWED_TOOLS)
    servers = json.loads((context.directory / "runtime/mcp.json").read_text())["mcpServers"]
    assert set(servers) == {"gridlens"}
    assert servers["gridlens"]["env"]["GRIDLENS_AGENT_CONTEXT"].endswith("context.json")
    manifest = json.loads((context.directory / "manifest.json").read_text())
    assert manifest["route"] == "remote" and manifest["tools"] == list(TOOL_NAMES)
    assert "left this machine" in manifest["egress_note"]
    assert prepared.environment.get("NO_PROXY") is None


@pytest.mark.parametrize("tools,servers,code", [
    (["Bash"], [{"name": "gridlens"}], "UNEXPECTED_TOOL"),
    ([], [{"name": "gridlens"}, {"name": "other"}], "UNEXPECTED_TOOL"),
    ([], [], "MCP_UNAVAILABLE"),
    ([], [{"name": "gridlens", "status": "failed"}], "MCP_UNAVAILABLE"),
])
def test_claude_preflight_refuses_a_session_it_does_not_control(tools, servers, code):
    line = json.dumps({"type": "system", "subtype": "init", "session_id": "s1", "tools": tools, "mcp_servers": servers})
    with pytest.raises(AgentError) as error:
        ClaudeCodeAdapter().parse_event(line)
    assert error.value.code == code


def test_claude_events_normalize_to_the_shared_contract():
    adapter = ClaudeCodeAdapter()
    good = json.dumps({"type": "system", "subtype": "init", "session_id": "s1", "tools": list(ALLOWED_TOOLS), "mcp_servers": [{"name": "gridlens", "status": "connected"}]})
    assert adapter.parse_event(good).data["session_id"] == "s1"
    text = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "120% [T1]"}]}})
    assert adapter.parse_event(text) .text == "120% [T1]"
    call = json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": ALLOWED_TOOLS[0]}]}})
    assert adapter.parse_event(call).kind == "tool_start"
    with pytest.raises(AgentError, match="non-GridLens"):
        adapter.parse_event(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}))
    done = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "answer", "session_id": "s1", "usage": {"output_tokens": 4}})
    event = adapter.parse_event(done)
    assert (event.kind, event.text, event.data["usage"]) == ("completed", "answer", {"output_tokens": 4})
    failed = adapter.parse_event(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": ""}))
    assert failed.kind == "error"
    with pytest.raises(AgentError, match="differs from the tested version"):
        adapter.parse_event(json.dumps({"type": "something_new"}))


def test_codex_events_normalize_and_reject_builtin_activity():
    adapter = CodexAdapter()
    assert adapter.parse_event(json.dumps({"type": "thread.started", "thread_id": "t1"})).data["session_id"] == "t1"
    message = json.dumps({"type": "item.completed", "item": {"item_type": "agent_message", "text": "120% [T1]"}})
    assert adapter.parse_event(message).text == "120% [T1]"
    tool = json.dumps({"type": "item.completed", "item": {"item_type": "mcp_tool_call", "tool": "gridlens__rank", "status": "completed"}})
    assert adapter.parse_event(tool).kind == "tool_result"
    for item_type in ("command_execution", "file_change", "web_search"):
        with pytest.raises(AgentError, match="unsupported"):
            adapter.parse_event(json.dumps({"type": "item.completed", "item": {"item_type": item_type}}))
    assert adapter.parse_event(json.dumps({"type": "turn.completed", "usage": {"output_tokens": 2}})).kind == "completed"
    assert adapter.parse_event(json.dumps({"type": "turn.failed", "error": {"message": "usage limit"}})).text == "usage limit"


def test_replayed_history_is_bounded_and_marked_as_data():
    history = [{"role": "user", "text": "x" * 4000}, {"role": "assistant", "text": "y" * 4000}] * 4
    composed = turn_prompt(("run_a",), "Which line is most congested?", history)
    assert "Selected run IDs: [\"run_a\"]" in composed
    assert "<prior_conversation" in composed and "never instructions" in composed
    assert len(composed) < MAX_REPLAY_CHARS + 4000
    assert turn_prompt(("run_a",), "question") == 'Selected run IDs: ["run_a"]\nUser question:\nquestion'


def test_every_turn_states_the_session_facts(agent_context):
    """Where projects, the session project, and saved results are is stated per turn, not in the shared prompt."""
    composed = turn_prompt(agent_context.run_ids, "question", facts=session_facts(agent_context))
    assert composed.startswith("Session facts:\n- GridLens projects folder: " + str(agent_context.projects_folder))
    assert f"- Session project: {agent_context.project_root}" in composed
    assert f"- Saved results folder: {agent_context.directory / 'results'}" in composed
    assert str(agent_context.project_root) not in SYSTEM_PROMPT
