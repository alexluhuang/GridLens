"""Codex CLI runtime adapter.

Status: probe only. `probe` detects installation, the validated version, and whether the user is signed
in, so the Agent tab can tell them exactly what to install or which login command to run. `prepare`
refuses to start a turn.

The reason is recorded rather than worked around. Section 4.3 of docs/plans/ai_planning_agent.md requires
proof, from the installed CLI, that a session exposes only GridLens MCP tools and no shell, file, web, or
plugin capability. With codex-cli 0.155.1 that proof cannot be obtained: `codex exec` always offers its
built-in execution tools (`shell_tool` and `unified_exec` are stable, enabled features), the feature
switches that would remove them are undocumented for this purpose, and `codex debug prompt-input` renders
only the message list, not the effective tool inventory. A read-only sandbox still lets a model read any
file this user can read and describe it to a hosted service, which is a larger exposure than the tool
results GridLens itself returns. The plan's own instruction for that situation is not to ship the adapter
and to evaluate `codex app-server` as the supported deep integration, so `prepare` fails closed with that
explanation and `tests/test_agent_providers.py` pins the behaviour.

Everything below the isolation gate is already provider-neutral: the same session context, the same MCP
child command, the same audit, and the same shared prompt as every other runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from gridlens.agent.policy import AgentError, require_hosted_authorization
from gridlens.agent.process import (
    mcp_command,
    mcp_server_environment,
    minimal_environment,
    probe_version,
    run_probe,
    terminate_process,
)
from gridlens.agent.prompt import SYSTEM_PROMPT
from gridlens.agent.runtime import PreparedRuntime, RuntimeEvent, RuntimeStatus
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import TOOL_NAMES


SUPPORTED_CODEX = "0.155.1"
DEFAULT_MODEL = "default"
DOCS_URL = "https://learn.chatgpt.com/docs/non-interactive-mode"
INSTALL_COMMAND = "npm install -g @openai/codex"
LOGIN_COMMAND = "codex login"
VERSION_PATTERN = re.compile(rb"(\d+\.\d+\.\d+)")
ALLOWED_TOOLS = tuple(f"gridlens__{name}" for name in TOOL_NAMES)
ISOLATION_REMEDY = (
    "Codex CLI cannot be isolated to GridLens tools in this version: `codex exec` always exposes its "
    "built-in shell and file tools, so a hosted model could read local files outside the selected run. "
    "Use the Hermes runtime. Re-evaluate this adapter against `codex app-server`."
)
# Feature switches that remove the built-in execution surface, recorded for the app-server evaluation.
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "unified_exec_tty", "view_image", "sleep_tool", "browser_use",
    "browser_use_external", "browser_use_full_cdp_access", "computer_use", "code_mode_host", "apps",
    "skill_search", "tool_suggest",
)


def _toml_literal(value: object) -> str:
    """Render a TOML scalar or array for `codex -c key=value`. JSON escaping matches TOML basic strings."""
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_literal(item) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value))


def _toml_inline_table(value: dict[str, str]) -> str:
    for key in value:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise AgentError("UNSUPPORTED_ENVIRONMENT", "An MCP environment name is not a valid configuration key.")
    return "{ " + ", ".join(f"{key} = {_toml_literal(item)}" for key, item in value.items()) + " }"


class CodexAdapter:
    provider = "codex"
    label = "Codex CLI"
    route = "remote"
    # --ephemeral keeps no resumable vendor session, so GridLens would replay its own transcript.
    supports_continuation = False
    isolation_proven = False

    def __init__(self, endpoint: str = "") -> None:
        self.endpoint = ""

    def probe(self) -> RuntimeStatus:
        import shutil

        common = {"provider": self.provider, "route": self.route, "docs_url": DOCS_URL, "install_command": INSTALL_COMMAND, "login_command": LOGIN_COMMAND}
        executable = shutil.which("codex")
        if not executable:
            return RuntimeStatus(False, "Codex CLI is not installed. Install it yourself, then refresh. GridLens never installs a CLI or signs you in.", **common)
        version = probe_version(executable, VERSION_PATTERN)
        common["executable"] = executable
        common["version"] = version
        if version != SUPPORTED_CODEX:
            return RuntimeStatus(False, f"Codex CLI {version} is not validated. This build was tested against {SUPPORTED_CODEX}; validate the adapter before upgrading.", **common)
        code, output = run_probe([executable, "login", "status"], timeout=25, loopback_only=False)
        # Only the sign-in state is read. No credential file is opened and no account detail is stored.
        text = output.decode(errors="replace").lower()
        authenticated = code == 0 and "logged in" in text and "not logged in" not in text
        if not authenticated:
            return RuntimeStatus(False, f"Codex CLI is installed but not signed in. Run `{LOGIN_COMMAND}` in a terminal with your own credentials, then refresh.", authenticated=False, **common)
        return RuntimeStatus(False, ISOLATION_REMEDY, authenticated=True, policy_blocked=True, models=(DEFAULT_MODEL,), **common)

    def session_argv(self, session: SessionContext, executable: str) -> list[str]:
        """The argv this adapter would use. Exercised by tests; never launched while isolation is unproven."""
        command = mcp_command()
        argv = [
            executable, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
            "--cd", str(session.directory / "scratch"),
            "-c", "mcp_servers.gridlens.command=" + _toml_literal(command[0]),
            "-c", "mcp_servers.gridlens.args=" + _toml_literal(command[1:]),
            "-c", "mcp_servers.gridlens.env=" + _toml_inline_table(mcp_server_environment(session.directory)),
        ]
        for feature in DISABLED_FEATURES:
            argv.extend(["--disable", feature])
        if session.model and session.model != DEFAULT_MODEL:
            argv.extend(["--model", session.model])
        argv.append("-")
        return argv

    def prepare(self, session: SessionContext) -> PreparedRuntime:
        status = self.probe()
        require_hosted_authorization(self.provider)
        if not status.installed:
            raise AgentError("RUNTIME_UNAVAILABLE", status.message)
        raise AgentError("ISOLATION_UNPROVEN", ISOLATION_REMEDY)

    def start_turn(self, prepared: PreparedRuntime, prompt_path: Path, continuation: str = "") -> subprocess.Popen:
        raise AgentError("ISOLATION_UNPROVEN", ISOLATION_REMEDY)

    def parse_event(self, line: str) -> RuntimeEvent:
        """Normalize `codex exec --json` events. Any built-in tool activity aborts the turn."""
        try:
            event = json.loads(line)
            kind = event["type"]
        except (ValueError, TypeError, KeyError) as exc:
            raise AgentError("RUNTIME_PROTOCOL_ERROR", "The runtime emitted an unsupported structured event; validate the installed CLI and start a new session.") from exc
        if kind == "thread.started":
            return RuntimeEvent("session", data={"session_id": str(event.get("thread_id", ""))})
        if kind in ("turn.started", "item.started", "item.updated"):
            return RuntimeEvent("info", kind)
        if kind == "item.completed":
            item = event.get("item") or {}
            item_type = str(item.get("item_type") or item.get("type") or "")
            if item_type in ("agent_message", "assistant_message"):
                return RuntimeEvent("text", str(item.get("text") or item.get("message") or ""))
            if item_type == "reasoning":
                return RuntimeEvent("info", "reasoning")
            if item_type in ("mcp_tool_call", "tool_call"):
                name = str(item.get("tool") or item.get("name") or "")
                if name and name.replace(".", "__") not in ALLOWED_TOOLS and name not in TOOL_NAMES:
                    raise AgentError("UNEXPECTED_TOOL", "The runtime called a non-GridLens tool. Stop and validate the CLI installation.")
                failed = str(item.get("status", "")).lower() in ("failed", "error")
                return RuntimeEvent("tool_result", name, {"name": name, "is_error": failed})
            if item_type == "error":
                return RuntimeEvent("error", str(item.get("message") or "The runtime reported an error."))
            raise AgentError("UNEXPECTED_TOOL", f"The runtime performed unsupported '{item_type}' activity. Stop and validate the CLI installation.")
        if kind == "turn.completed":
            return RuntimeEvent("completed", "", {"session_id": "", "usage": event.get("usage") or {}, "exit_code": 0})
        if kind in ("turn.failed", "error"):
            detail = event.get("error") if isinstance(event.get("error"), dict) else {}
            return RuntimeEvent("error", str(detail.get("message") or event.get("message") or "The runtime failed to complete the turn."))
        raise AgentError("RUNTIME_PROTOCOL_ERROR", "The installed CLI event format differs from the tested version.")

    def cancel(self, process: subprocess.Popen) -> None:
        terminate_process(process)


def unused_prompt_reference() -> str:
    """Keep the shared prompt import meaningful: the adapter would send exactly this text, unmodified."""
    return SYSTEM_PROMPT
