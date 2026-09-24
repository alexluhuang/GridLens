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
from gridlens.agent.prompt import session_facts, turn_prompt
from gridlens.agent.runtime import RuntimeAdapter, RuntimeEvent
from gridlens.agent.session import SessionContext, append_event, scoped_path, write_json
from gridlens.agent.tools import ToolService


MAX_PROMPT_CHARS = 12_000
# A long study can make dozens of tool calls in one turn, and each call's events count toward this.
MAX_TURN_BYTES = 16 * 1024 * 1024
MAX_REPLAY_TURNS = 6
READ_CHUNK_BYTES = 16384
# Keep only the tail of stderr: it is a diagnostic, not a result.
STDERR_TAIL_BYTES = 8192
MAX_EVENT_BYTES = 128 * 1024
POLL_SECONDS = 0.1
EXIT_WAIT_SECONDS = 2
# Questions whose answer could be mistaken for spare capacity: margins, headroom, extra MW, or transfer limits.
CAPACITY_QUESTION = re.compile(r"\b(?:margin|capacity|headroom|carry|ttc|fcitc|atc)\b|\bmore\s+mw\b|\btransfer\s+(?:capability|limit)", re.IGNORECASE)


class AgentController:
    """Synchronous worker API; the GUI calls it from a QThread.

    The controller owns the canonical conversation record. A runtime may resume its own session, but its
    history is never the only copy: when an adapter reports supports_continuation as False, the next turn
    is composed from this record instead.
    """
    def __init__(self, context: SessionContext, adapter: RuntimeAdapter, *, timeout: float = 3600) -> None:
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

    def restore(self, messages: list[dict], events: list[dict]) -> None:
        """Load saved messages and events into this controller; open_history uses the state for another turn."""
        self.history = [
            {"role": item["role"], "text": item["text"]}
            for item in messages if item.get("role") in ("user", "assistant") and isinstance(item.get("text"), str)
        ]
        self.continuation = ""
        if self.history and self.history[-1]["role"] == "assistant" and getattr(self.adapter, "supports_continuation", True):
            for item in reversed(events):
                if item.get("kind") == "completed" and isinstance(item.get("data"), dict):
                    session_id = item["data"].get("session_id")
                    self.continuation = session_id if isinstance(session_id, str) else ""
                    break

    def _write_prompt(self, prompt: str) -> Path:
        """Write this turn's prompt to its own file in the session folder, and return the path.

        Prompts go through a file rather than the command line so that no question, however it is
        punctuated, can reach a shell. A runtime that cannot resume gets a bounded replay of GridLens's
        own transcript folded in here.
        """
        prompt_dir = scoped_path(self.context.directory, "prompts", directory=True)
        prompt_dir.mkdir(exist_ok=True, mode=0o700)
        prompt_path = scoped_path(prompt_dir, f"{time.time_ns()}.txt")
        replay = [] if getattr(self.adapter, "supports_continuation", True) and self.continuation else self.history[-MAX_REPLAY_TURNS:]
        content = turn_prompt(tuple(self.context.run_ids), prompt, replay, session_facts(self.context))
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
            request = group_mean_request(prompt)
            if request and len(self.context.run_ids) == 1:
                group_by, facility = request
                current = sources[prior_calls:]
                complete = any(group_mean_source(row, group_by, facility) and not row["result"]["data"].get("truncated") for row in current)
                if not complete:
                    emit(RuntimeEvent("tool_start", "rank_groups (verified scope)"))
                    summary = ToolService(self.context).rank_groups(self.context.run_ids[0], group=RANK_GROUPS_GROUP[group_by], object=RANK_GROUPS_OBJECT[facility], magnitude=0)
                    emit(RuntimeEvent("tool_result", "rank_groups (verified scope)", {"is_error": bool(summary["error"])}))
                    sources = session_sources(self.context.directory)
            top_count = top_line_area_request(prompt)
            if top_count and len(self.context.run_ids) == 1:
                if ranked_line_source(sources[prior_calls:], self.context.run_ids[0], top_count) is None:
                    emit(RuntimeEvent("tool_start", "rank (verified areas)"))
                    ranking = ToolService(self.context).rank(self.context.run_ids[0], magnitude=top_count, fields=list(AREA_FIELDS))
                    emit(RuntimeEvent("tool_result", "rank (verified areas)", {"is_error": bool(ranking["error"])}))
                    sources = session_sources(self.context.directory)
            final = normalize_citations(final, sources)
            final = cite_uncited_turn(final, sources[prior_calls:])
            final = disclose_truncated_results(final, sources[prior_calls:])
            final = disclose_tool_failures(final, sources[prior_calls:])
            final = qualify_capacity_answer(final, prompt)
            final = disclose_generated_output(final, sources[prior_calls:])
            final = verified_group_mean_answer(final, prompt, sources[prior_calls:], self.context.run_ids)
            final = verified_top_line_areas(final, prompt, sources[prior_calls:], self.context.run_ids)
            previous_answer = next((item["text"] for item in reversed(self.history[:-1]) if item["role"] == "assistant"), "")
            final = verified_singular_line_area(final, prompt, previous_answer, sources, self.context.run_ids)
            final = audited_row_scope_answer(final, prompt, sources)
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
    """Return answer with a note for each call this turn that returned only part of its matching rows.

    A call is partial when its page stopped before the last matching row, or when its rows were too
    large to show inline and were saved to a file instead.
    """
    notes = []
    for row in turn_sources:
        data = ((row.get("result") or {}).get("data") or {})
        if data.get("truncated"):
            notes.append(f"[{row['call_id']}] returned {data.get('returned', 0):,} of {data.get('total_matching', 0):,} matching rows; {_more_rows(row)}")
        if data.get("result_file"):
            notes.append(f"[{row['call_id']}] showed {data.get('inline_rows', 0):,} rows inline; its complete result is in {data.get('rows_file') or data['result_file']}")
    if not notes:
        return answer
    return answer.rstrip() + "\n\nGridLens audit: " + "; ".join(notes[:10]) + "."


def _more_rows(row: dict) -> str:
    """Say how to get the rest of a partial result: a larger magnitude for the rank tools, else an offset."""
    if row.get("tool") in ("rank", "rank_groups"):
        return "more are available with a larger magnitude, or magnitude=0 for all"
    return f"more are available from offset {((row.get('result') or {}).get('data') or {}).get('next_offset') or 0:,}"


def disclose_tool_failures(answer: str, turn_sources: list[dict]) -> str:
    """Return an answer with a rebuild note for stale-cache turn_sources in run_turn."""
    ids = [row["call_id"] for row in turn_sources if ((row.get("result") or {}).get("error") or {}).get("code") == "ANALYSIS_NOT_BUILT"]
    if ids:
        return answer.rstrip() + "\n\nGridLens note: " + ", ".join(f"[{call_id}]" for call_id in ids[:10]) + " reported ANALYSIS_NOT_BUILT. The current cache is unavailable; no returned rows do not establish that congestion is absent. Build it with run_analysis or Build / refresh analysis, and ask again."
    return answer


def group_mean_request(question: str) -> tuple[str, str] | None:
    """Map a question to (group, facility), or None; run_turn uses it for whole-run means."""
    words = question.casefold()
    if not re.search(r"\b(mean|average)\b", words) or not re.search(r"\b(loading|utilization)\b", words):
        return None
    # A named area or voltage cutoff needs a parsed filter; never substitute an all-area result.
    if re.search(r"\b(?:in|within|for)\s+(?:the\s+)?(?:control\s+)?area\s+\S+", words):
        return None
    cutoff = re.search(r"\b(at least|above|below|under|over)\s+(\d+(?:\.\d+)?)\s*kv\b", words)
    if cutoff and (cutoff.group(1) != "at least" or float(cutoff.group(2)) != 50.0):
        return None
    if re.search(r"\b(?:in|within)\s+(?!run[_ -]?\w+|(?:this|the)\s+(?:run|case|project|system)|all\b|descending\b|ascending\b)[a-z][\w-]*", words):
        return None
    if re.search(r"\bvoltage\s+(groups?|categories|classes)\b|\b\d+\s*[-–]\s*\d+\s*kv\b", words):
        group_by = "voltage"
    elif re.search(r"\b(control\s+)?areas?\b", words):
        group_by = "area"
    else:
        return None
    all_types = bool(re.search(r"\b(all facility types|all branch types|including transformers)\b", words))
    if "transformer" in words and "non-transformer" not in words and not all_types:
        return None
    return group_by, "all" if all_types else "line"


# The rank_groups arguments that answer a whole-run group-mean question, by the question's grouping and scope.
RANK_GROUPS_GROUP = {"area": "control_area", "voltage": "voltage_class"}
RANK_GROUPS_OBJECT = {"line": "branches", "all": "both"}
# The fields an audited top-line ranking needs so area answers can name both endpoints.
AREA_FIELDS = ("control_area", "bus_name")


def group_mean_source(row: dict, group_by: str, facility: str) -> bool:
    """Return whether an audited rank_groups call computed mean maximum loading over every facility of each group.

    It must use the question's group and objects, no qualifiers, no comparison run, and statistic='mean'
    of max_utilization_pct.
    """
    arguments = row.get("arguments") or {}
    return (
        row.get("tool") == "rank_groups" and row.get("outcome") == "ok"
        and not arguments.get("filters") and not arguments.get("compare_run_id")
        and (arguments.get("group"), arguments.get("object"), arguments.get("metric"), arguments.get("statistic"))
        == (RANK_GROUPS_GROUP[group_by], RANK_GROUPS_OBJECT.get(facility), "max_utilization_pct", "mean")
    )


def verified_group_mean_answer(answer: str, question: str, turn_sources: list[dict], run_ids: tuple[str, ...]) -> str:
    """Return an answer from complete turn_sources for a question/run_ids; run_turn uses it for group means."""
    request = group_mean_request(question)
    if request is None or len(run_ids) != 1:
        return answer
    group_by, facility = request
    if group_by == "voltage":
        title, mean_label = "Voltage groups", "voltage-group"
    else:
        title, mean_label = "Control areas", "control-area"
    matching = [row for row in turn_sources if group_mean_source(row, group_by, facility) and row["arguments"].get("run_id") == run_ids[0]]
    if not matching:
        if any(((row.get("result") or {}).get("error") or {}).get("code") == "ANALYSIS_NOT_BUILT" for row in turn_sources):
            return "The analysis cache is unavailable. Use Build / refresh analysis and ask again."
        needed = f"rank_groups(group='{RANK_GROUPS_GROUP[group_by]}', object='{RANK_GROUPS_OBJECT.get(facility)}')"
        ranked = [row for row in turn_sources if row.get("tool") == "rank" and row.get("outcome") == "ok"]
        if ranked:
            data = ranked[-1]["result"]["data"]
            return f"I cannot verify whole-run {mean_label} means from ranked rows. [{ranked[-1]['call_id']}] returned {data['returned']:,} of {data['total_matching']:,} facilities. A complete {needed} result is needed."
        return f"I cannot verify whole-run {mean_label} means without a complete {needed} result."
    source = matching[-1]
    data = source["result"]["data"]
    if data.get("truncated") or data.get("returned") != data.get("total_matching"):
        return f"[{source['call_id']}] returned only {data.get('returned', 0)} of {data.get('total_matching', 0)} {title.lower()}; I cannot rank every category from it. Narrow the filters and ask again."
    groups = sorted(((row["group"], float(row["value"]), row["count"]) for row in data["rows"]), key=lambda group: -group[1])
    count = data.get("objects_used", 0)
    noun = "facility" if count == 1 else "facilities"
    lines = [f"{title}, ranked by mean maximum observed loading across all {count:,} matching {noun} ({facility}, all control areas, at least 50 kV) [{source['call_id']}]:"]
    lines.extend(f"- {label}: {value:.1f}% ({members:,} facilities)" for label, value, members in groups)
    convergence = data.get("convergence") or {}
    if convergence.get("failed"):
        lines.append(f"The cache includes {convergence['failed']} failed or non-converged cases among {convergence['total']} recorded cases; their rows are not excluded from these maxima.")
    lines.append("These means use all matching facilities, not just the displayed ranked rows.")
    return "\n".join(lines)


def top_line_area_request(question: str) -> int | None:
    """Return requested top-line count for area questions; run_turn uses it to fetch a ranking."""
    words = question.casefold()
    match = re.search(r"\b(?:top|first)\s+(\d+)\b", words)
    if not match or not re.search(r"\bcongested\b", words) or not re.search(r"\blines\b", words):
        return None
    if not re.search(r"\b(?:control\s+)?areas?\b", words) or re.search(r"\b(?:mean|average)\b", words):
        return None
    if re.search(r"\b(?:in|within|for)\s+(?:the\s+)?(?:control\s+)?area\s+\S+", words):
        return None
    if re.search(r"\b(?:in|within)\s+(?!run[_ -]?\w+|(?:this|the)\s+(?:run|case|project|system)|all\b)[a-z][\w-]*", words):
        return None
    count = int(match.group(1))
    return count if count > 0 else None


def ranked_line_source(sources: list[dict], run_id: str, count: int) -> dict | None:
    """Find an audited, unqualified line ranking by maximum loading, with endpoint areas, of at least count rows."""
    for source in reversed(sources):
        args = source.get("arguments") or {}
        data = ((source.get("result") or {}).get("data") or {})
        if source.get("tool") != "rank" or source.get("outcome") != "ok" or args.get("filters") or args.get("compare_run_id"):
            continue
        if (args.get("run_id"), args.get("metric"), args.get("object"), args.get("order")) != (run_id, "max_utilization_pct", "branches", "descending"):
            continue
        if not set(AREA_FIELDS) <= set(args.get("fields") or ()):
            continue
        if data.get("returned", 0) >= count or data.get("returned") == data.get("total_matching"):
            return source
    return None


def verified_top_line_areas(answer: str, question: str, turn_sources: list[dict], run_ids: tuple[str, ...]) -> str:
    """Return audited top-line endpoint areas for question/run_ids; run_turn replaces model guesses."""
    count = top_line_area_request(question)
    if count is None or len(run_ids) != 1:
        return answer
    source = ranked_line_source(turn_sources, run_ids[0], count)
    if source is None:
        return "I cannot verify the requested top-line areas from a complete ranked result. Ask again after refreshing the analysis."
    data = source["result"]["data"]
    rows = data["rows"][:count]
    if not rows:
        return f"No eligible lines were found in the selected run [{source['call_id']}]."
    lines = [f"Top {len(rows)} congested lines by maximum observed loading, with both endpoint control areas where they differ [{source['call_id']}]:"]
    for index, row in enumerate(rows, 1):
        areas = ", ".join(row.get("control_area") or ["unknown"])
        loading = "unknown loading" if row.get("value") is None else f"{float(row['value']):.1f}%"
        lines.append(f"{index}. {row['object']}: {areas} ({loading}).")
    if len(rows) < count:
        lines.append(f"Only {data['total_matching']:,} eligible lines matched the run scope.")
    return "\n".join(lines)


def verified_singular_line_area(answer: str, question: str, previous_answer: str, sources: list[dict], run_ids: tuple[str, ...]) -> str:
    """Use a prior top-line audit to answer 'that line' area follow-ups in run_turn."""
    words = question.casefold()
    if len(run_ids) != 1 or not re.search(r"\b(?:that|this) line\b", words) or not re.search(r"\b(?:control\s+)?areas?\b", words):
        return answer
    if not re.search(r"\bmost congested line\b", previous_answer.casefold()):
        return "I cannot identify which line you mean from the previous answer. Name its buses and circuit."
    source = ranked_line_source(sources, run_ids[0], 1)
    if source is None or not source["result"]["data"]["rows"]:
        return "I cannot verify that line's area from an audited ranking. Ask for the most congested line again."
    row = source["result"]["data"]["rows"][0]
    prior = " ".join(previous_answer.casefold().split())
    endpoints = [str(name or "").casefold() for name in row.get("bus_name") or ()]
    if any(endpoint and " ".join(endpoint.split()) not in prior for endpoint in endpoints):
        return "The line named in the previous answer does not match the audited top line. Name its buses and circuit."
    areas = ", ".join(row.get("control_area") or ["unknown"])
    return f"{row['object']} has endpoint control area(s): {areas} [{source['call_id']}]."


def audited_row_scope_answer(answer: str, question: str, sources: list[dict]) -> str:
    """Replace answer to a row-count question using sources; run_turn avoids model memory this way."""
    words = question.casefold()
    if not re.search(r"\b(rows?|results?)\b", words) or not re.search(r"\b(return\w*|display\w*|truncat\w*|limit|omit\w*|remaining|shown|view|used|based)\b", words):
        return answer
    requested_ids = {call.upper() for call in re.findall(r"\bT\d+\b", question, re.IGNORECASE)}
    candidates = [row for row in sources if row.get("call_id") in requested_ids] if requested_ids else [row for row in sources if "returned" in ((row.get("result") or {}).get("data") or {})]
    if not candidates:
        return "No audited tool result matches that call ID." if requested_ids else answer
    selected = candidates if requested_ids else candidates[-1:]
    lines = []
    for row in selected:
        result = row.get("result") or {}
        data = result.get("data") or {}
        error = result.get("error") or {}
        call_id = row["call_id"]
        by_magnitude = row.get("tool") in ("rank", "rank_groups")
        requested = (row.get("arguments") or {}).get("magnitude") if by_magnitude else data.get("limit", (row.get("arguments") or {}).get("limit"))
        if error:
            lines.append(f"[{call_id}] returned no rows because the call failed with {error.get('code', 'UNKNOWN')}.")
        else:
            kind = {"rank_groups": "group rows", "rank": "object rows"}.get(row.get("tool"), "rows")
            lines.append(f"[{call_id}] returned {data.get('returned', 0):,} of {data.get('total_matching', 0):,} matching {kind}; truncated: {bool(data.get('truncated'))}.")
            if row.get("tool") == "rank_groups":
                lines.append(f"Its group statistics were computed from all {data.get('objects_used', 0):,} matching objects before limiting group rows.")
        if requested is not None:
            requested_text = "all rows" if requested == 0 else f"{requested:,}" if isinstance(requested, int) else str(requested)
            if by_magnitude:
                lines.append(f"Requested magnitude: {requested_text}.")
            else:
                lines.append(f"Requested row limit: {requested_text}; offset: {data.get('offset') or 0:,}.")
        if data.get("next_offset") is not None:
            lines.append("More matching rows are " + _more_rows(row).removeprefix("more are ") + ".")
        if data.get("result_file"):
            lines.append(f"{data.get('inline_rows', 0):,} rows were shown inline; the complete result is in {data.get('rows_file') or data['result_file']}.")
    lines.append("GridLens applies no maximum row count: limit=0, or magnitude=0 for rank and rank_groups, returns every matching row, and offset pages the other tools.")
    return "\n".join(lines)


def disclose_generated_output(answer: str, turn_sources: list[dict]) -> str:
    """Return an answer with a note when this turn read the output of a generated script, which nothing has validated."""
    read = any(any("generated script's folder" in warning for warning in (row.get("result") or {}).get("warnings") or []) for row in turn_sources)
    if not read:
        return answer
    return answer.rstrip() + "\n\nGridLens note: This answer uses the output of a generated script, which no deterministic GridLens tool has validated. Treat it as untrusted until it is checked."


def qualify_capacity_answer(answer: str, question: str) -> str:
    """Return an answer that qualifies thermal margin for capacity, headroom, and transfer questions in run_turn."""
    if not CAPACITY_QUESTION.search(question):
        return answer
    return answer.rstrip() + "\n\nGridLens note: Observed thermal margin alone cannot establish how much more load, generation, or transfer a system can accommodate; that requires a separate power-flow study."
