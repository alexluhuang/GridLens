"""The Hermes Agent runtime adapter, driving a local model served by Ollama.

This is the validated runtime. It builds a throwaway Hermes profile inside the session folder that
contains only the GridLens MCP server, then launches `hermes chat` against it with the prompt in a file
rather than on the command line.

The adapter is pinned to one tested CLI version and refuses any other. Guessing at a changed event format
would be worse than refusing, because the failure would surface as a wrong answer rather than an error.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from gridlens.agent.policy import AgentError, local_endpoint, ollama_json, verify_model
from gridlens.agent.process import (
    mcp_command,
    mcp_server_environment,
    minimal_environment,
    probe_version,
    terminate_process,
)
from gridlens.agent.prompt import SYSTEM_PROMPT
from gridlens.agent.runtime import PreparedRuntime, RuntimeEvent, RuntimeStatus
from gridlens.agent.session import SessionContext, scoped_path, write_json
from gridlens.agent.tools import TOOL_NAMES


SUPPORTED_HERMES = "0.21.4"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
# A turn may start a GridPACK run and wait for it through get_job, so it gets an hour; Stop ends it sooner.
TURN_TIMEOUT_SECONDS = 3600
DOCS_URL = "https://hermes-agent.nousresearch.com/docs/getting-started/installation/"
OLLAMA_DOCS_URL = "https://docs.ollama.com/quickstart"
VERSION_PATTERN = re.compile(rb"Hermes Agent v(\d+\.\d+\.\d+)")
# The profile and the command line have to agree, so the turn cap is named once. A study that creates a
# project, configures and starts a run, waits for it, and analyzes it needs a few dozen tool calls.
MAX_TURNS = 60
# One GridLens tool call may scan a multi-gigabyte result or wait for a job, so it may take this long.
MCP_TOOL_TIMEOUT_SECONDS = 1800


def _profile_config(session: SessionContext, command: list[str]) -> dict:
    """Build the throwaway Hermes profile: this session's model, and only the GridLens tool server.

    Every switch here turns something off. What is left is one model endpoint and one MCP server, so the
    CLI has no skills, plugins, memory, telemetry, update checks, or tool search to fall back on.
    """
    return {
        "model": {"default": session.model, "provider": "custom", "base_url": session.endpoint + "/v1"},
        "agent": {"max_turns": MAX_TURNS, "system_prompt": SYSTEM_PROMPT, "api_max_retries": 1},
        "toolsets": ["gridlens"], "fallback_providers": [],
        "compression": {"enabled": False},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "plugins": {"enabled": []}, "hooks": {},
        # The profile has no command-execution tools; prevent optional command-scanner downloads.
        "security": {"tirith_enabled": False, "allow_lazy_installs": False},
        "auth": {"adopt_external_logins": False},
        "updates": {"check": False},
        "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
        "tools": {"tool_search": {"enabled": "off"}},
        "mcp_servers": {"gridlens": {
            "command": command[0], "args": command[1:], "env": mcp_server_environment(session.directory),
            "timeout": MCP_TOOL_TIMEOUT_SECONDS,
            "tools": {"include": list(TOOL_NAMES), "resources": False, "prompts": False},
        }},
    }


class HermesAdapter:
    """Drive the Hermes CLI against a local Ollama endpoint, through an isolated session profile."""
    provider = "hermes"
    label = "Hermes Agent + local Ollama"
    route = "loopback_only"
    supports_continuation = True
    isolation_proven = True

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT) -> None:
        self.endpoint = endpoint

    def probe(self) -> RuntimeStatus:
        # Signing in does not apply: inference is served by the user's own loopback Ollama service.
        """Report the Hermes version, the loopback endpoint, and the installed local models."""
        common = {"provider": self.provider, "route": self.route, "docs_url": DOCS_URL, "install_command": "ollama pull MODEL", "login_command": ""}
        executable = shutil.which("hermes")
        if not executable:
            return RuntimeStatus(False, "Hermes Agent is not installed. Install it yourself using its installation guide, then refresh. GridLens never installs a CLI or a model.", **common)
        common["executable"] = executable
        version = ""
        try:
            endpoint = local_endpoint(self.endpoint)
            version = probe_version(executable, VERSION_PATTERN)
            common["version"] = version
            if version != SUPPORTED_HERMES:
                return RuntimeStatus(False, f"Hermes {version} is not validated. This build supports {SUPPORTED_HERMES}; validate the adapter before upgrading.", endpoint=endpoint, **common)
            ollama_json(endpoint, "/api/version")
            inventory = ollama_json(endpoint, "/api/tags")
            models = tuple(sorted({item["name"] for item in inventory.get("models", []) if isinstance(item, dict) and isinstance(item.get("name"), str) and not item.get("remote_host") and "cloud" not in item["name"].lower().split(":")[-1]}))
            if not models:
                return RuntimeStatus(False, "No local Ollama models found. Install a model with tool support yourself (ollama pull MODEL), then refresh.", endpoint=endpoint, **common)
            return RuntimeStatus(True, f"Hermes {version}; Ollama reachable on loopback. Signing in does not apply to local Ollama. Model tool support is checked before anything is sent.", endpoint=endpoint, models=models, **common)
        except (AgentError, OSError, subprocess.TimeoutExpired) as exc:
            common.setdefault("version", version)
            return RuntimeStatus(False, str(exc) if isinstance(exc, AgentError) else "Hermes did not respond. Run `hermes --version` in a terminal, then refresh.", **common)

    def prepare(self, session: SessionContext) -> PreparedRuntime:
        """Write an isolated profile and the session manifest, then fix the launch command."""
        status = self.probe()
        if not status.ready:
            raise AgentError("RUNTIME_UNAVAILABLE", status.message)
        if session.endpoint != status.endpoint or session.model not in status.models:
            raise AgentError("MODEL_UNAVAILABLE", "Refresh the runtime and select an installed local model.")
        verify_model(session.endpoint, session.model)
        profile = scoped_path(session.directory, "runtime/profiles/gridlens", directory=True)
        scratch = scoped_path(session.directory, "scratch", directory=True)
        empty = scoped_path(session.directory, "runtime/empty", directory=True)
        for path in (profile, scratch, empty):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        command = mcp_command()
        # JSON is valid YAML; no YAML dependency is needed to write the isolated profile.
        write_json(scoped_path(profile, "config.yaml"), _profile_config(session, command))
        environment = minimal_environment()
        environment.update(
            HERMES_HOME=str(profile), HERMES_BUNDLED_SKILLS=str(empty), HERMES_BUNDLED_PLUGINS=str(empty),
            CUSTOM_BASE_URL=session.endpoint + "/v1", CUSTOM_API_KEY="ollama",
            OPENAI_BASE_URL=session.endpoint + "/v1", OPENAI_API_KEY="ollama",
        )
        argv = (
            status.executable, "chat", "--oneshot", "--format", "stream-json", "--provider", "custom",
            "--model", session.model, "--toolsets", "gridlens", "--ignore-rules", "--no-restore-cwd",
            "--max-turns", str(MAX_TURNS), "--run-budget", str(TURN_TIMEOUT_SECONDS), "--source", "tool", "--cli",
        )
        write_json(session.directory / "manifest.json", {
            "runtime": self.provider, "runtime_version": status.version, "model": session.model,
            "endpoint": session.endpoint, "route": self.route, "command_template": list(argv) + ["--query-file", "<session prompt file>"],
            "mcp_command": command, "tools": list(TOOL_NAMES), "profile": "runtime/profiles/gridlens",
            "egress_note": "Inference stayed on this machine: the resolved endpoint was loopback and proxies were disabled for the runtime process.",
        })
        return PreparedRuntime(session, argv, environment, scratch)

    def start_turn(self, prepared: PreparedRuntime, prompt_path: Path, continuation: str = "") -> subprocess.Popen:
        """Re-verify the model, then launch one turn against the session prompt file."""
        verify_model(prepared.context.endpoint, prepared.context.model)
        argv = [*prepared.command, "--query-file", str(prompt_path)]
        if continuation:
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+", continuation):
                raise AgentError("INVALID_CONTINUATION", "Start a new session; the runtime returned an invalid continuation ID.")
            argv.extend(["--resume", continuation])
        return subprocess.Popen(argv, cwd=prepared.cwd, env=prepared.environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

    def parse_event(self, line: str) -> RuntimeEvent:
        """Normalize one Hermes stream-json event, refusing any non-GridLens tool."""
        try:
            event = json.loads(line)
            kind = event["type"]
        except (ValueError, TypeError, KeyError) as exc:
            raise AgentError("RUNTIME_PROTOCOL_ERROR", "Hermes emitted an unsupported structured event; inspect the local runtime and start a new session.") from exc
        if kind == "system" and event.get("subtype") == "init":
            # When the runtime reports its effective inventory, refuse a session GridLens does not control.
            exposed = event.get("tools") if isinstance(event.get("tools"), list) else []
            if any(not str(name).startswith("mcp__gridlens__") for name in exposed):
                raise AgentError("UNEXPECTED_TOOL", "The runtime exposed non-GridLens tools. Stop and validate the Hermes installation.")
            return RuntimeEvent("session", data={"session_id": event.get("session_id", "")})
        if kind == "text":
            return RuntimeEvent("text", str(event.get("text", "")))
        if kind in ("tool_use", "tool_result"):
            name = event.get("name", "")
            if name not in {f"mcp__gridlens__{tool}" for tool in TOOL_NAMES}:
                raise AgentError("UNEXPECTED_TOOL", "The runtime exposed a non-GridLens tool. Stop and validate the Hermes installation.")
            return RuntimeEvent("tool_start" if kind == "tool_use" else "tool_result", name, {"name": name, "is_error": bool(event.get("is_error", False))})
        if kind == "result":
            return RuntimeEvent("error" if event.get("exit_code") or event.get("error") else "completed", str(event.get("text") or event.get("error") or ""), {"session_id": event.get("session_id", ""), "usage": event.get("tokens", {}), "exit_code": event.get("exit_code", 0)})
        raise AgentError("RUNTIME_PROTOCOL_ERROR", "The installed Hermes event format differs from the tested version.")

    def cancel(self, process: subprocess.Popen) -> None:
        """Terminate Hermes and the MCP server it started."""
        terminate_process(process)
