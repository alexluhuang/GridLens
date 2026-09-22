"""The contract every agent runtime adapter implements.

This module holds no provider logic. It defines what GridLens needs to know about a runtime, what a
normalized event from one looks like, and what a prepared launch looks like. Keeping those shapes here is
what lets the session store, the controller, the tool layer, and the GUI stay free of provider-specific
code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Protocol

from gridlens.agent.session import SessionContext


@dataclass(frozen=True)
class RuntimeStatus:
    """What the Agent tab needs in order to describe one runtime without knowing which runtime it is."""

    ready: bool
    message: str
    executable: str = ""
    version: str = ""
    endpoint: str = ""
    models: tuple[str, ...] = ()
    provider: str = "hermes"
    route: str = "loopback_only"
    # None means signing in does not apply, as for local inference served on loopback.
    authenticated: bool | None = None
    # True when the CLI is installed and usable but this deployment's data policy forbids the route.
    policy_blocked: bool = False
    install_command: str = ""
    login_command: str = ""
    docs_url: str = ""

    @property
    def installed(self) -> bool:
        return bool(self.executable)

    @property
    def remote(self) -> bool:
        return self.route != "loopback_only"


@dataclass(frozen=True)
class RuntimeEvent:
    """One normalized event from a runtime: a kind the controller knows, plus text and payload."""
    kind: str
    text: str = ""
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedRuntime:
    """Everything needed to launch one turn, fixed at session preparation rather than per turn."""
    context: SessionContext
    command: tuple[str, ...]
    environment: dict[str, str]
    cwd: Path


class RuntimeAdapter(Protocol):
    """One contract for every runtime. Nothing above this layer parses provider-specific output."""

    provider: str
    label: str
    route: str
    # False when the runtime keeps no resumable session, so the controller replays its own transcript.
    supports_continuation: bool

    def probe(self) -> RuntimeStatus:
        """Report whether this runtime is installed, signed in, and permitted here."""

    def prepare(self, session: SessionContext) -> PreparedRuntime:
        """Fix the launch command for a session, and write its manifest. Refuse if unusable."""

    def start_turn(self, prepared: PreparedRuntime, prompt_path: Path, continuation: str = "") -> subprocess.Popen:
        """Launch one turn in its own process group, reading the prompt from a file."""

    def parse_event(self, line: str) -> RuntimeEvent:
        """Normalize one line of runtime output. Raise rather than guess at an unknown shape."""

    def cancel(self, process: subprocess.Popen) -> None:
        """Terminate the runtime and every child it started, including the MCP server."""
