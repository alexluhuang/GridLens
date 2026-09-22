"""The turn loop, and the canonical record of the conversation.

The controller owns the transcript. A runtime may keep its own session and resume it, but that copy is
never the only one: an adapter that cannot resume safely gets a bounded replay of this record instead.
The loop reads the child process through a selector under a wall-clock deadline and byte caps, normalizes
every line through the adapter, audits it, and terminates the whole process group on stop, timeout, or
error.

`normalize_citations` is the other half of the trust story. An answer may cite only call IDs that appear
in the audit, and anything else is rewritten so the reader can see it was invented.
"""
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
READ_CHUNK_BYTES = 16384
# Keep only the tail of stderr: it is a diagnostic, not a result.
STDERR_TAIL_BYTES = 8192
MAX_EVENT_BYTES = 128 * 1024
POLL_SECONDS = 0.1
EXIT_WAIT_SECONDS = 2


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
        """Return a name for the runtime that is safe to show a user."""
        return getattr(self.adapter, "label", None) or getattr(self.adapter, "provider", None) or "The agent runtime"

    def cancel(self) -> None:
        """Ask the turn in flight to stop at its next checkpoint."""
        self.cancelled.set()

    def _write_prompt(self, prompt: str) -> Path:
        """Write this turn's prompt to its own file in the session folder, and return the path.

        Prompts go through a file rather than the command line so that no question, however it is
        punctuated, can reach a shell. A runtime that cannot resume gets a bounded replay of GridLens's
        own transcript folded in here.
        """
        prompt_dir = scoped_path(self.context.directory, "prompts", directory=True)
        prompt_dir.mkdir(exist_ok=True, mode=0o700)
        prompt_path = scoped_path(prompt_dir, f"{time.time_ns()}.txt")
        replay = [] if getattr(self.adapter, "supports_continuation", True) else self.history[-MAX_REPLAY_TURNS:]
        content = turn_prompt(tuple(self.context.run_ids), prompt, replay)
        with os.fdopen(os.open(prompt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
            handle.write(content)
        return prompt_path

    def _consume_output(self, process, emit: Callable[[RuntimeEvent], None], buffers: dict) -> tuple[str | None, int]:
        """Read the runtime until it finishes, and return its answer and exit code.

        Reads both streams under one deadline and one byte budget, so a runtime cannot outlast the turn
        limit or flood the session by writing to whichever stream is unwatched. stderr is kept only as a
        tail for diagnostics; stdout is split into lines and handed to the adapter.
        """
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
                for key, _ in selector.select(timeout=POLL_SECONDS):
                    chunk = os.read(key.fileobj.fileno(), READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > MAX_TURN_BYTES:
                        raise AgentError("OUTPUT_LIMIT", "The runtime exceeded the output limit; start a new session.")
                    channel = key.data
                    if channel == "stderr":
                        buffers[channel] = (buffers[channel] + chunk)[-STDERR_TAIL_BYTES:]
                        continue
                    buffers[channel] += chunk
                    if len(buffers[channel]) > MAX_EVENT_BYTES:
                        raise AgentError("OUTPUT_LIMIT", "A runtime event exceeded the size limit.")
                    while b"\n" in buffers[channel]:
                        line, buffers[channel] = buffers[channel].split(b"\n", 1)
                        if not line.strip():
                            continue
                        answer = self._handle_line(line, emit, spoken)
                        if answer is not None:
                            final = answer
            return final, process.wait(timeout=EXIT_WAIT_SECONDS)

    def _handle_line(self, line: bytes, emit: Callable[[RuntimeEvent], None], spoken: list[str]) -> str | None:
        """Audit and dispatch one runtime event, returning the final answer when the turn completes."""
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
        if event.kind != "completed":
            return None
        self.continuation = event.data.get("session_id", "") if getattr(self.adapter, "supports_continuation", True) else ""
        write_json(self.context.directory / "usage.json", event.data.get("usage", {}))
        # Some runtimes report the answer only as streamed text, not in the final event.
        return event.text or "".join(spoken)[-MAX_PROMPT_CHARS:]

    def run_turn(self, prompt: str, emit: Callable[[RuntimeEvent], None]) -> str:
        """Run one turn to completion and return the cited answer."""
        if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            raise AgentError("INVALID_PROMPT", f"Enter a question of at most {MAX_PROMPT_CHARS:,} characters.")
        process = None
        buffers = {"stdout": b"", "stderr": b""}
        self.context.set_status("running")
        self.context.message("user", prompt)
        try:
            prior_calls = len(session_sources(self.context.directory))
            if self.prepared is None:
                self.prepared = self.adapter.prepare(self.context)
            if self.cancelled.is_set():
                raise AgentError("CANCELLED", "Turn stopped.")
            prompt_path = self._write_prompt(prompt)
            self.history.append({"role": "user", "text": prompt})
            process = self.adapter.start_turn(self.prepared, prompt_path, self.continuation)
            final, return_code = self._consume_output(process, emit, buffers)
            if buffers["stdout"].strip() or return_code or final is None or not final.strip():
                raise AgentError("RUNTIME_INCOMPLETE", f"{self.runtime_label} exited without a complete answer. Check the runtime and the selected model, then start a new session.")
            sources = session_sources(self.context.directory)
            final = normalize_citations(final, sources)
            final = cite_uncited_turn(final, sources[prior_calls:])
            final = disclose_truncated_results(final, sources[prior_calls:])
            final = disclose_tool_failures(final, sources[prior_calls:])
            final = qualify_capacity_answer(final, prompt)
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
    """Read the completed tool calls a session has recorded so far."""
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


def cite_uncited_turn(answer: str, turn_sources: list[dict]) -> str:
    """Return an answer with current successful audit IDs when run_turn finds no model citation."""
    if any(row.get("outcome") == "error" for row in turn_sources):
        return answer
    ids = [row["call_id"] for row in turn_sources if row.get("outcome") == "ok"]
    if not ids or any(f"[{call_id}]" in answer for call_id in ids):
        return answer
    return answer.rstrip() + "\n\nSources consulted (model omitted inline citations): " + ", ".join(f"[{call_id}]" for call_id in ids[:10])


def disclose_truncated_results(answer: str, turn_sources: list[dict]) -> str:
    """Return an answer with a scope note for truncated turn_sources in run_turn."""
    ids = [row["call_id"] for row in turn_sources if ((row.get("result") or {}).get("data") or {}).get("truncated")]
    if not ids or "truncat" in answer.lower() or "partial" in answer.lower():
        return answer
    return answer.rstrip() + "\n\nGridLens note: Tool results " + ", ".join(f"[{call_id}]" for call_id in ids[:10]) + " were truncated by row limits; other facilities may be omitted."


def disclose_tool_failures(answer: str, turn_sources: list[dict]) -> str:
    """Return an answer with a rebuild note for stale-cache turn_sources in run_turn."""
    ids = [row["call_id"] for row in turn_sources if ((row.get("result") or {}).get("error") or {}).get("code") == "ANALYSIS_NOT_BUILT"]
    if not ids:
        return answer
    return answer.rstrip() + "\n\nGridLens note: " + ", ".join(f"[{call_id}]" for call_id in ids[:10]) + " reported ANALYSIS_NOT_BUILT. The current cache is unavailable; no returned rows do not establish that congestion is absent. Use Build / refresh analysis and ask again."


def qualify_capacity_answer(answer: str, question: str) -> str:
    """Return an answer that qualifies thermal margin for capacity questions in run_turn."""
    if not any(term in question.casefold() for term in ("margin", "capacity")):
        return answer
    return answer.rstrip() + "\n\nGridLens note: Observed thermal margin alone cannot establish how much more load, generation, or transfer a system can accommodate; that requires a separate power-flow study."
