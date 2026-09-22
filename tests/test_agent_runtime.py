from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from gridlens.agent.controller import AgentController, normalize_citations
from gridlens.agent.hermes import HermesAdapter
from gridlens.agent.policy import AgentError, local_endpoint, verify_model
from gridlens.agent.process import mcp_command, minimal_environment
from gridlens.agent.prompt import SYSTEM_PROMPT
from gridlens.agent.runtime import PreparedRuntime, RuntimeStatus


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
