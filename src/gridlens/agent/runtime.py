from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Protocol

from gridlens.agent.session import SessionContext


@dataclass(frozen=True)
class RuntimeStatus:
    ready: bool
    message: str
    executable: str = ""
    version: str = ""
    endpoint: str = ""
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeEvent:
    kind: str
    text: str = ""
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedRuntime:
    context: SessionContext
    command: tuple[str, ...]
    environment: dict[str, str]
    cwd: Path


class RuntimeAdapter(Protocol):
    def probe(self) -> RuntimeStatus: ...
    def prepare(self, session: SessionContext) -> PreparedRuntime: ...
    def start_turn(self, prepared: PreparedRuntime, prompt_path: Path, continuation: str = "") -> subprocess.Popen: ...
    def parse_event(self, line: str) -> RuntimeEvent: ...
    def cancel(self, process: subprocess.Popen) -> None: ...
