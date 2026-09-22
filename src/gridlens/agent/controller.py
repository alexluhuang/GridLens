from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import selectors
import threading
import time
from typing import Callable

from gridlens.agent.policy import AgentError
from gridlens.agent.prompt import turn_prompt
from gridlens.agent.runtime import RuntimeAdapter, RuntimeEvent
from gridlens.agent.session import SessionContext, append_event, scoped_path, write_json


MAX_PROMPT_CHARS = 12_000
MAX_TURN_BYTES = 2 * 1024 * 1024
MAX_REPLAY_TURNS = 6


class AgentController:
    """Synchronous worker API; the GUI calls it from a QThread.

    The controller owns the canonical conversation record. A runtime may resume its own session, but its
    history is never the only copy: when an adapter reports supports_continuation as False, the next turn
    is composed from this record instead.
    """
    def __init__(self, context: SessionContext, adapter: RuntimeAdapter, *, timeout: float = 300) -> None:
        self.context = context
        self.adapter = adapter
        self.timeout = timeout
        self.prepared = None
        self.continuation = ""
        self.history: list[dict] = []
        self.cancelled = threading.Event()

    @property
    def runtime_label(self) -> str:
        return getattr(self.adapter, "label", None) or getattr(self.adapter, "provider", None) or "The agent runtime"

    def cancel(self) -> None:
        self.cancelled.set()

    def run_turn(self, prompt: str, emit: Callable[[RuntimeEvent], None]) -> str:
        if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            raise AgentError("INVALID_PROMPT", f"Enter a question of at most {MAX_PROMPT_CHARS:,} characters.")
        process = None
        buffers = {"stdout": b"", "stderr": b""}
        self.context.set_status("running")
        self.context.message("user", prompt)
        try:
            if self.prepared is None:
                self.prepared = self.adapter.prepare(self.context)
            if self.cancelled.is_set():
                raise AgentError("CANCELLED", "Turn stopped.")
            prompt_dir = scoped_path(self.context.directory, "prompts", directory=True)
            prompt_dir.mkdir(exist_ok=True, mode=0o700)
            prompt_path = scoped_path(prompt_dir, f"{time.time_ns()}.txt")
            replay = [] if getattr(self.adapter, "supports_continuation", True) else self.history[-MAX_REPLAY_TURNS:]
            content = turn_prompt(tuple(self.context.run_ids), prompt, replay)
            with os.fdopen(os.open(prompt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
                handle.write(content)
            self.history.append({"role": "user", "text": prompt})
            process = self.adapter.start_turn(self.prepared, prompt_path, self.continuation)
            deadline = time.monotonic() + self.timeout
            total = 0
            final = None
            spoken: list[str] = []
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    if self.cancelled.is_set():
                        raise AgentError("CANCELLED", "Turn stopped.")
                    if time.monotonic() >= deadline:
                        raise AgentError("TIMEOUT", "The local model exceeded the turn time limit. Try a smaller question or another model.")
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 16384)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > MAX_TURN_BYTES:
                            raise AgentError("OUTPUT_LIMIT", "The runtime exceeded the output limit; start a new session.")
                        channel = key.data
                        if channel == "stderr":
                            buffers[channel] = (buffers[channel] + chunk)[-8192:]
                            continue
                        buffers[channel] += chunk
                        if len(buffers[channel]) > 128 * 1024:
                            raise AgentError("OUTPUT_LIMIT", "A runtime event exceeded the size limit.")
                        while b"\n" in buffers[channel]:
                            line, buffers[channel] = buffers[channel].split(b"\n", 1)
                            if not line.strip():
                                continue
                            try:
                                event = self.adapter.parse_event(line.decode("utf-8"))
                            except AgentError:
                                append_event(self.context.directory, "runtime_events.jsonl", {"kind": "invalid_event", "text": line.decode("utf-8", errors="replace")[:2048]})
                                raise
                            append_event(self.context.directory, "runtime_events.jsonl", asdict(event))
                            emit(event)
                            if event.kind == "text" and event.text:
                                spoken.append(event.text)
                            if event.kind == "error":
                                raise AgentError("RUNTIME_ERROR", event.text[:2000] or f"{self.runtime_label} failed to complete the turn.")
                            if event.kind == "completed":
                                # Some runtimes report the answer only as streamed text, not in the final event.
                                final = event.text or "".join(spoken)[-MAX_PROMPT_CHARS:]
                                self.continuation = event.data.get("session_id", "") if getattr(self.adapter, "supports_continuation", True) else ""
                                write_json(self.context.directory / "usage.json", event.data.get("usage", {}))
                return_code = process.wait(timeout=2)
            if buffers["stdout"].strip() or return_code or final is None or not final.strip():
                raise AgentError("RUNTIME_INCOMPLETE", f"{self.runtime_label} exited without a complete answer. Check the runtime and the selected model, then start a new session.")
            final = normalize_citations(final, session_sources(self.context.directory))
            self.history.append({"role": "assistant", "text": final})
            self.context.message("assistant", final)
            self.context.set_status("completed")
            return final
        except Exception as exc:
            code = exc.code if isinstance(exc, AgentError) else "RUNTIME_ERROR"
            detail = str(exc) if isinstance(exc, AgentError) else f"{self.runtime_label} failed. Check the runtime and its model, then start a new session."
            self.context.set_status("cancelled" if code == "CANCELLED" else "failed", detail)
            append_event(self.context.directory, "runtime_events.jsonl", {"kind": "error", "code": code, "text": detail})
            emit(RuntimeEvent("error", detail, {"code": code}))
            self.continuation = ""
            raise AgentError(code, detail) from exc
        finally:
            if process is not None:
                self.adapter.cancel(process)
                process.stdout.close()
                process.stderr.close()
            if buffers["stderr"]:
                append_event(self.context.directory, "runtime_events.jsonl", {"kind": "diagnostic", "text": buffers["stderr"].decode("utf-8", errors="replace")})


def session_sources(directory: Path) -> list[dict]:
    path = scoped_path(directory, "tool_calls.jsonl")
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
                if event.get("phase") == "completed":
                    rows.append(event)
            except ValueError:
                continue  # A running tool may still be appending the final line.
    return rows


def normalize_citations(text: str, sources: list[dict]) -> str:
    """Normalize explicit call references, and flag IDs absent from the audit."""
    known = {row["call_id"] for row in sources}
    def replace(match):
        identifier = (match[1] or match[2]).upper()
        return f"[{identifier}]" if identifier in known else f"[{identifier}: invalid source]"

    return re.sub(
        r"\[[\s\u200b\ufeff]*(?:Call\s+)?(T\d+)[\s\u200b\ufeff]*\]|(?:\(\s*)?\bcall_id\s*[:=]?\s*(T\d+)\b(?:\s*\))?",
        replace,
        text, flags=re.IGNORECASE,
    )
