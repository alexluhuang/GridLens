"""Claude Code runtime adapter.

Claude Code is classified remote: project-derived text leaves this machine. The adapter is therefore
inert unless the hosted-provider gate in gridlens.agent.policy is opened, which is a governance decision
recorded in docs/security_ceii.md, not a code change.

Isolation is established from the CLI itself rather than from a list of nominally safe flags. The
`--restricted --tools ""` combination removes the built-in command, code, and web tools and ignores user,
project, and local settings; `--strict-mcp-config` ignores every MCP server except the one GridLens
supplies. The first structured event of every turn reports the effective tool and MCP inventory, and
prepare/parse refuse to continue when it contains anything other than GridLens tools.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

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
from gridlens.agent.session import SessionContext, scoped_path, write_json
from gridlens.agent.tools import TOOL_NAMES


SUPPORTED_CLAUDE_CODE = "2.1.278"
DEFAULT_MODEL = "default"
DOCS_URL = "https://code.claude.com/docs/en/cli-usage"
INSTALL_COMMAND = "curl -fsSL https://claude.ai/install.sh | bash"
LOGIN_COMMAND = "claude auth login"
VERSION_PATTERN = re.compile(rb"(\d+\.\d+\.\d+)")
ALLOWED_TOOLS = tuple(f"mcp__gridlens__{name}" for name in TOOL_NAMES)
BLOCKED_BUILTIN_TOOLS = (
    "Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep", "WebFetch", "WebSearch",
    "Task", "Agent", "TodoWrite", "KillShell", "BashOutput",
)


def _assert_tool_inventory(tools: object, servers: object) -> None:
    """Fail closed when the effective session exposes anything GridLens did not supply."""
    unexpected = sorted({str(name) for name in tools or [] if not str(name).startswith("mcp__gridlens__")})
    if unexpected:
        raise AgentError("UNEXPECTED_TOOL", f"The runtime exposed non-GridLens tools ({', '.join(unexpected[:5])}). Stop and validate the CLI installation.")
    names = {str(item.get("name")) for item in servers or [] if isinstance(item, dict)}
    if names - {"gridlens"}:
        raise AgentError("UNEXPECTED_TOOL", "The runtime loaded an unrelated MCP server. Stop and validate the CLI installation.")
    if "gridlens" not in names:
        raise AgentError("MCP_UNAVAILABLE", "The GridLens tool server did not start. Check the GridLens installation, then start a new session.")
    for item in servers or []:
        status = str(item.get("status", "connected")).lower() if isinstance(item, dict) else ""
        if isinstance(item, dict) and item.get("name") == "gridlens" and status not in ("", "connected", "ready"):
            raise AgentError("MCP_UNAVAILABLE", f"The GridLens tool server reported status '{status}'. Start a new session.")


class ClaudeCodeAdapter:
    """Drive Claude Code in print mode, restricted to the GridLens MCP tools."""
    provider = "claude"
    label = "Claude Code"
    route = "remote"
    # --no-session-persistence keeps vendor-side history out of play, so GridLens replays its own record.
    supports_continuation = False

    def __init__(self, endpoint: str = "") -> None:
        self.endpoint = ""

    def probe(self) -> RuntimeStatus:
        import shutil

        common = {"provider": self.provider, "route": self.route, "docs_url": DOCS_URL, "install_command": INSTALL_COMMAND, "login_command": LOGIN_COMMAND}
        executable = shutil.which("claude")
        if not executable:
            return RuntimeStatus(False, "Claude Code is not installed. Install it yourself, then refresh. GridLens never installs a CLI or signs you in.", **common)
        version = probe_version(executable, VERSION_PATTERN)
        common["executable"] = executable
        common["version"] = version
        if version != SUPPORTED_CLAUDE_CODE:
            return RuntimeStatus(False, f"Claude Code {version} is not validated. This build was tested against {SUPPORTED_CLAUDE_CODE}; validate the adapter before upgrading.", **common)
        code, output = run_probe([executable, "auth", "status", "--json"], timeout=25, loopback_only=False)
        authenticated = False
        try:
            # Read only the boolean. Account address, organization, and tokens are never parsed or stored.
            authenticated = bool(json.loads(output or b"{}").get("loggedIn"))
        except (ValueError, AttributeError):
            authenticated = False
        if code != 0 or not authenticated:
            return RuntimeStatus(False, f"Claude Code is installed but not signed in. Run `{LOGIN_COMMAND}` in a terminal with your own credentials, then refresh.", authenticated=False, **common)
        try:
            require_hosted_authorization(self.provider)
        except AgentError as exc:
            return RuntimeStatus(False, str(exc), authenticated=True, policy_blocked=True, **common)
        return RuntimeStatus(
            True,
            f"Claude Code {version}, signed in with your own credentials. Remote route: your questions and every tool "
            "result GridLens returns leave this machine. The session folder records exactly what was sent.",
            authenticated=True, models=(DEFAULT_MODEL,), **common,
        )

    def prepare(self, session: SessionContext) -> PreparedRuntime:
        status = self.probe()
        if not status.ready:
            raise AgentError("RUNTIME_UNAVAILABLE", status.message)
        require_hosted_authorization(self.provider)
        if session.route != "remote" or not session.remote_acknowledged:
            raise AgentError("REMOTE_NOT_ACKNOWLEDGED", "Confirm the remote-data acknowledgement in the Agent tab before starting a hosted session.")
        runtime_dir = scoped_path(session.directory, "runtime", directory=True)
        scratch = scoped_path(session.directory, "scratch", directory=True)
        for path in (runtime_dir, scratch):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        command = mcp_command()
        mcp_path = scoped_path(runtime_dir, "mcp.json")
        write_json(mcp_path, {"mcpServers": {"gridlens": {"command": command[0], "args": command[1:], "env": mcp_server_environment(session.directory)}}})
        prompt_path = scoped_path(runtime_dir, "system_prompt.txt")
        prompt_path.write_text(SYSTEM_PROMPT, encoding="utf-8")
        argv = [
            status.executable, "--print",
            "--output-format", "stream-json", "--verbose",
            "--restricted", "--tools", "",
            "--strict-mcp-config", "--mcp-config", str(mcp_path),
            "--allowedTools", *ALLOWED_TOOLS,
            "--disallowedTools", *BLOCKED_BUILTIN_TOOLS,
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--disable-slash-commands", "--no-session-persistence",
            "--system-prompt", SYSTEM_PROMPT,
            "--add-dir", str(scratch),
        ]
        if session.model and session.model != DEFAULT_MODEL:
            argv.extend(["--model", session.model])
        environment = minimal_environment(loopback_only=False)
        environment.update(
            DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1",
            DISABLE_BUG_COMMAND="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        )
        write_json(session.directory / "manifest.json", {
            "runtime": self.provider, "runtime_version": status.version, "model": session.model,
            "endpoint": "", "route": "remote",
            "command_template": [*argv, "<session prompt on stdin>"],
            "mcp_command": command, "tools": list(TOOL_NAMES), "profile": "runtime/mcp.json",
            "egress_note": "Prompts, the GridLens system prompt, and every tool result returned to the model left this machine through the vendor CLI. Provider-added fields, transport headers, and retries are not recorded.",
        })
        return PreparedRuntime(session, tuple(argv), environment, scratch)

    def start_turn(self, prepared: PreparedRuntime, prompt_path: Path, continuation: str = "") -> subprocess.Popen:
        argv = [*prepared.command, "--session-id", str(uuid4())]
        with prompt_path.open("rb") as handle:
            return subprocess.Popen(
                argv, cwd=prepared.cwd, env=prepared.environment, stdin=handle,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            )

    def parse_event(self, line: str) -> RuntimeEvent:
        try:
            event = json.loads(line)
            kind = event["type"]
        except (ValueError, TypeError, KeyError) as exc:
            raise AgentError("RUNTIME_PROTOCOL_ERROR", "The runtime emitted an unsupported structured event; validate the installed CLI and start a new session.") from exc
        if kind == "system":
            if event.get("subtype") == "init":
                _assert_tool_inventory(event.get("tools"), event.get("mcp_servers"))
                return RuntimeEvent("session", data={"session_id": str(event.get("session_id", ""))})
            return RuntimeEvent("info", str(event.get("subtype", "system")))
        if kind in ("assistant", "user"):
            message = event.get("message") or {}
            blocks = message.get("content") if isinstance(message.get("content"), list) else []
            texts, tool_name, tool_error = [], "", False
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    texts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_use":
                    name = str(block.get("name", ""))
                    if name not in ALLOWED_TOOLS:
                        raise AgentError("UNEXPECTED_TOOL", "The runtime called a non-GridLens tool. Stop and validate the CLI installation.")
                    tool_name = name
                elif block.get("type") == "tool_result":
                    tool_name = tool_name or "mcp__gridlens__(result)"
                    tool_error = bool(block.get("is_error"))
                    return RuntimeEvent("tool_result", tool_name, {"name": tool_name, "is_error": tool_error})
            if tool_name:
                return RuntimeEvent("tool_start", tool_name, {"name": tool_name, "is_error": False})
            return RuntimeEvent("text", "".join(texts))
        if kind == "result":
            failed = bool(event.get("is_error")) or event.get("subtype") != "success"
            text = str(event.get("result") or "")
            return RuntimeEvent(
                "error" if failed else "completed",
                text or ("The runtime reported " + str(event.get("subtype", "an error"))),
                {"session_id": str(event.get("session_id", "")), "usage": event.get("usage") or {}, "exit_code": 1 if failed else 0},
            )
        if kind in ("stream_event", "rate_limit_event", "control_response", "prompt_suggestion"):
            return RuntimeEvent("info", kind)
        raise AgentError("RUNTIME_PROTOCOL_ERROR", "The installed CLI event format differs from the tested version.")

    def cancel(self, process: subprocess.Popen) -> None:
        terminate_process(process)
