"""How long each turn of a conversation took, and how many tokens the model used, from the session's audit.

A turn starts when the user's message is recorded and ends when the answer, or an error, is. Between the
two, the tool audit records when each GridLens tool call started and ended, and the runtime's completion
event carries the model's token counts. So the accounting keeps no state of its own: it is computed from
`transcript.jsonl`, `tool_calls.jsonl`, and `runtime_events.jsonl` whenever it is wanted, and it is the
same for a conversation read back later as for one just finished.

Time in tools includes waiting: `get_status` can wait for a background job to end. The rest of a turn's
time is the model's and the runtime's: inference, and the runtime's own work between calls.

Hermes reports tokens as input (prompt tokens it did not read from its cache), cache_read, cache_write, and
output. The prompt the model read is input plus cache_read plus cache_write; total adds output.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import statistics

from gridlens.agent.policy import AgentError
from gridlens.agent.session import scoped_path


TOKEN_FIELDS = ("input", "cache_read", "cache_write", "output")
MAX_AUDIT_BYTES = 256 * 1024 * 1024


def _lines(directory: Path, name: str) -> list[dict]:
    """Return the JSON objects of one audit file, skipping a line still being written."""
    try:
        path = scoped_path(directory, name)
    except AgentError:
        return []
    if not path.is_file() or path.stat().st_size > MAX_AUDIT_BYTES:
        return []
    rows = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def tokens(usage: dict | None) -> dict | None:
    """Return a runtime's token counts in one shape, with the prompt and total, or None when it reported none."""
    if not isinstance(usage, dict) or not usage:
        return None
    counts = {name: int(usage.get(name) or 0) for name in TOKEN_FIELDS}
    counts["prompt"] = counts["input"] + counts["cache_read"] + counts["cache_write"]
    counts["total"] = int(usage.get("total") or counts["prompt"] + counts["output"])
    return counts


def turn_accounting(directory: Path) -> list[dict]:
    """Return one record per turn of the conversation in directory, oldest first.

    Each record gives the turn's number, question, start and end, outcome (answered, error, or
    unfinished), its seconds, the seconds spent in GridLens tools and per tool, the seconds left to the
    model and runtime, the model's tokens, and its output tokens per second of that time.
    """
    messages = _lines(directory, "transcript.jsonl")
    calls = [row for row in _lines(directory, "tool_calls.jsonl") if row.get("phase") == "completed"]
    events = _lines(directory, "runtime_events.jsonl")
    starts = [(index, _time(item.get("timestamp"))) for index, item in enumerate(messages) if item.get("role") == "user"]
    turns = []
    for position, (index, started) in enumerate(starts):
        if started is None:
            continue
        following = starts[position + 1][1] if position + 1 < len(starts) else None

        def inside(value: object) -> bool:
            moment = _time(value)
            return moment is not None and moment >= started and (following is None or moment < following)

        answer = next((item for item in messages[index + 1:] if item.get("role") == "assistant" and inside(item.get("timestamp"))), None)
        error = next((event for event in events if event.get("kind") == "error" and inside(event.get("timestamp"))), None)
        completed = [event for event in events if event.get("kind") == "completed" and inside(event.get("timestamp"))]
        turn_calls = [row for row in calls if inside(row.get("started_at"))]
        per_tool: dict[str, dict] = {}
        tool_seconds = 0.0
        for row in turn_calls:
            begin, end = _time(row.get("started_at")), _time(row.get("ended_at"))
            seconds = max(0.0, (end - begin).total_seconds()) if begin and end else 0.0
            tool_seconds += seconds
            entry = per_tool.setdefault(str(row.get("tool", "?")), {"calls": 0, "seconds": 0.0})
            entry["calls"] += 1
            entry["seconds"] = round(entry["seconds"] + seconds, 3)
        ended = _time((answer or error or {}).get("timestamp"))
        outcome = "answered" if answer else "error" if error else "unfinished"
        seconds = (ended - started).total_seconds() if ended else None
        model_seconds = max(0.0, seconds - tool_seconds) if seconds is not None else None
        counts = tokens((completed[-1].get("data") or {}).get("usage")) if completed else None
        rate = round(counts["output"] / model_seconds, 1) if counts and model_seconds else None
        turns.append({
            "turn": len(turns) + 1, "question": " ".join(str(messages[index].get("text", "")).split())[:200],
            "started_at": messages[index].get("timestamp"), "ended_at": (answer or error or {}).get("timestamp"), "outcome": outcome,
            "seconds": round(seconds, 3) if seconds is not None else None, "tool_calls": len(turn_calls), "tool_seconds": round(tool_seconds, 3),
            "model_seconds": round(model_seconds, 3) if model_seconds is not None else None, "tools": per_tool,
            "tokens": counts, "output_tokens_per_second": rate,
        })
    return turns


def totals(turns: list[dict]) -> dict:
    """Sum turns' time and tokens, and give the median time of a turn."""
    timed = [turn["seconds"] for turn in turns if turn["seconds"] is not None]
    counted = [turn["tokens"] for turn in turns if turn["tokens"]]
    summed = {name: sum(item[name] for item in counted) for name in (*TOKEN_FIELDS, "prompt", "total")} if counted else None
    return {
        "turns": len(turns), "answered": sum(turn["outcome"] == "answered" for turn in turns),
        "seconds": round(sum(timed), 3), "median_seconds": round(statistics.median(timed), 3) if timed else None,
        "tool_calls": sum(turn["tool_calls"] for turn in turns), "tool_seconds": round(sum(turn["tool_seconds"] for turn in turns), 3),
        "model_seconds": round(sum(turn["model_seconds"] or 0.0 for turn in turns), 3), "tokens": summed,
    }


def duration(seconds: float | None) -> str:
    """Write a number of seconds for a person, such as "3 min 12 s", "4.2 s", or "19 ms"."""
    if seconds is None:
        return "unknown"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes} min {rest} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def summary(turn: dict) -> str:
    """Describe one turn's time and tokens in one line, such as "3 min 12 s · 88,588 tokens"."""
    parts = [duration(turn["seconds"])]
    if turn["tokens"]:
        parts.append(f"{turn['tokens']['total']:,} tokens")
    return " · ".join(parts)


def sentence(turn: dict) -> str:
    """Describe one turn's time and tokens in a sentence for the conversation record."""
    text = f"This turn took {duration(turn['seconds'])}"
    if turn["tool_calls"]:
        text += f", {duration(turn['tool_seconds'])} of it in {turn['tool_calls']} GridLens tool call{'s' if turn['tool_calls'] != 1 else ''}"
    text += "."
    counts = turn["tokens"]
    if counts:
        text += f" The model read {counts['prompt']:,} prompt tokens ({counts['cache_read']:,} from its cache) and wrote {counts['output']:,}."
    else:
        text += " The runtime reported no token counts."
    return text
