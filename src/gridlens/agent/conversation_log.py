"""The readable record of one conversation: `conversation.md` in its session folder.

The session folder holds the conversation as several machine-readable audit files, each written by a
different part of GridLens: the controller writes the messages, the tool server the tool calls, the
runtime adapter the runtime's events. None of them alone shows what happened. `write_conversation_log`
merges them, in time order, into one Markdown file a person can read: every question, every tool call
with its arguments and its complete result, every background job a call started, every error, and every
answer. The file is derived, so it is rewritten whole after each turn and never read back by GridLens.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from gridlens.agent.policy import AgentError
from gridlens.agent.session import CONVERSATION_LOG, FOCUS_FILE, scoped_path
from gridlens.system import files


# An audit file larger than this is not merged into the log; the log says so and names the file.
MAX_SOURCE_BYTES = 64 * 1024 * 1024
# One tool result longer than this is cut in the log; the complete result stays in tool_calls.jsonl.
MAX_RESULT_CHARS = 50_000
MAX_ARGUMENT_CHARS = 20_000

FILES = (
    (CONVERSATION_LOG, "this record, rewritten after each turn from the files below"),
    ("transcript.jsonl", "each question and answer, one JSON line each"),
    ("tool_calls.jsonl", "each GridLens tool call, with its arguments and complete result"),
    ("runtime_events.jsonl", "everything the agent runtime reported, including the answer as it was typed"),
    ("results/", "complete results too large to send to the model, as JSON and CSV"),
    ("generated/", "analysis scripts Clarke proposed, and the output of those you ran"),
    ("prompts/", "the exact text sent to the model for each question"),
    ("runtime/", "the private Hermes profile GridLens builds for this conversation (internal)"),
    ("context.json, focus.json, manifest.json", "the model and runtime, the project and runs in focus, and the launch command"),
    ("status.json, usage.json", "the state of the last turn, and the model's token counts"),
)


def _local_time(value: object) -> str:
    """Show an ISO timestamp in local time to the second, or the value unchanged when it is not one."""
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(value or "")


def _duration(start: object, end: object) -> str:
    """Return the time between two ISO timestamps in words, or "" when either is missing."""
    try:
        seconds = (datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))).total_seconds()
    except (TypeError, ValueError):
        return ""
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s"


def _fence(text: str) -> str:
    """Return a code fence longer than any run of backticks in text, so the text cannot close it."""
    longest, run = 0, 0
    for character in text:
        run = run + 1 if character == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def _block(text: str, language: str = "") -> str:
    """Return text as a fenced code block."""
    fence = _fence(text)
    return f"{fence}{language}\n{text}\n{fence}"


def _json(value: object) -> str:
    """Pretty-print a JSON value for the log."""
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _read_json(directory: Path, name: str) -> dict:
    """Return a JSON object from the session folder, or {} when it is missing, unreadable, or too large."""
    try:
        path = scoped_path(directory, name)
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (AgentError, OSError, ValueError):
        return {}


def _read_lines(directory: Path, name: str, notes: list[str]) -> list[dict]:
    """Return the JSON lines of an audit file, noting in notes a file too large to merge."""
    try:
        path = scoped_path(directory, name)
        if not path.is_file():
            return []
        if path.stat().st_size > MAX_SOURCE_BYTES:
            notes.append(f"{name} is larger than {MAX_SOURCE_BYTES // (1024 * 1024)} MB, so it is not merged here; open it directly.")
            return []
        rows = []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue  # A tool still running may be appending its line.
                if isinstance(value, dict):
                    rows.append(value)
        return rows
    except (AgentError, OSError):
        return []


def _header(directory: Path, notes: list[str]) -> list[str]:
    """Describe the conversation: when it began, the runtime and model, and where it is focused."""
    context = _read_json(directory, "context.json")
    focus = _read_json(directory, FOCUS_FILE) or context
    manifest = _read_json(directory, "manifest.json")
    stamp = str(context.get("session_id") or directory.name).split("_", 1)[0]
    try:
        started_text = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        started_text = "unknown"
    runtime = str(context.get("runtime") or manifest.get("runtime") or "unknown")
    if manifest.get("runtime_version"):
        runtime += f" {manifest['runtime_version']}"
    runs = ", ".join(str(run) for run in focus.get("run_ids") or []) or "none"
    lines = [
        "# Clarke conversation",
        "",
        f"- Started: {started_text}",
        f"- Runtime: {runtime}",
        f"- Model: {context.get('model', 'unknown')}",
        f"- Project in focus: {focus.get('project_root') or 'none'}",
        f"- Runs in focus: {runs}",
        f"- Folder: {directory}",
        "",
        "This file is written by GridLens from the audit files in this folder. It contains your questions, the",
        "answers, and grid data read from your projects, so treat it as sensitive.",
        "",
        "Files in this folder:",
        "",
    ]
    lines.extend(f"- `{name}`: {meaning}" for name, meaning in FILES)
    lines.append("")
    lines.extend(f"> {note}" for note in notes)
    return lines


def _tool_call(row: dict, started: dict | None) -> list[str]:
    """Describe one tool call: its ID, tool, outcome, duration, arguments, and result."""
    call_id = row.get("call_id", "?")
    tool = row.get("tool", "?")
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    error = result.get("error") or row.get("error") or {}
    outcome = row.get("outcome", "unknown")
    duration = _duration(row.get("started_at"), row.get("ended_at"))
    title = f"### Tool call {call_id}: {tool} ({outcome}" + (f", {duration}" if duration else "") + ")"
    lines = [title, "", f"Called at {_local_time(row.get('started_at'))}.", ""]
    if error:
        lines += [f"Error {error.get('code', 'UNKNOWN')}: {error.get('remedy', '')}", ""]
    arguments = _json(row.get("arguments", (started or {}).get("arguments", {})))
    if len(arguments) > MAX_ARGUMENT_CHARS:
        arguments = arguments[:MAX_ARGUMENT_CHARS] + "\n… (cut; see tool_calls.jsonl)"
    lines += ["Arguments:", "", _block(arguments, "json"), ""]
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    for job in _jobs(data):
        lines += [f"Started background job {job['job_id']} ({job.get('kind', 'job')}); its record is in {job['folder']}.", ""]
    text = _json(result)
    if len(text) > MAX_RESULT_CHARS:
        where = data.get("rows_file") or data.get("result_file")
        pointer = "the complete result is in tool_calls.jsonl" + (f" and {where}" if where else "")
        text = text[:MAX_RESULT_CHARS] + f"\n… (cut at {MAX_RESULT_CHARS:,} characters; {pointer})"
    lines += ["Result:", "", _block(text, "json"), ""]
    return lines


def _jobs(data: dict) -> list[dict]:
    """Return the background jobs a tool result reports starting, with the folder each is recorded in."""
    if not data.get("job_id"):
        return []
    rows = [row for row in data.get("rows") or [] if isinstance(row, dict) and row.get("job_id") == data["job_id"]]
    job = rows[0] if rows else {"job_id": data["job_id"]}
    folder = Path(str(job["project_root"])) / "agent/jobs" / job["job_id"] if job.get("project_root") else f"agent/jobs/{job['job_id']} of the project"
    return [{**job, "folder": folder}]


def _entries(directory: Path, notes: list[str]) -> list[tuple[str, int, list[str]]]:
    """Return every message, tool call, script run, and error of the conversation as (time, order, lines)."""
    entries = []
    for index, item in enumerate(_read_lines(directory, "transcript.jsonl", notes)):
        role = item.get("role")
        text = str(item.get("text", ""))
        heading = "## You" if role == "user" else "## Clarke" if role == "assistant" else f"## {str(role).title()}"
        body = _block(text) if role == "user" else text
        entries.append((str(item.get("timestamp", "")), 0 if role == "user" else 3, [f"{heading} · {_local_time(item.get('timestamp'))}", "", body, ""]))
    started: dict[str, dict] = {}
    completed: list[dict] = []
    for row in _read_lines(directory, "tool_calls.jsonl", notes):
        if row.get("phase") == "started":
            started[str(row.get("call_id"))] = row
        elif row.get("phase") == "completed":
            completed.append(row)
    finished = {str(row.get("call_id")) for row in completed}
    for row in completed:
        entries.append((str(row.get("started_at", "")), 1, _tool_call(row, started.get(str(row.get("call_id"))))))
    for call_id, row in started.items():
        if call_id not in finished:
            entries.append((str(row.get("started_at", "")), 1, [f"### Tool call {call_id}: {row.get('tool', '?')} (did not finish)", "", "Arguments:", "", _block(_json(row.get("arguments", {})), "json"), ""]))
    for event in _read_lines(directory, "runtime_events.jsonl", notes):
        if event.get("kind") == "error":
            entries.append((str(event.get("timestamp", "")), 2, [f"**Error** ({event.get('code', 'RUNTIME_ERROR')}) at {_local_time(event.get('timestamp'))}: {event.get('text', '')}", ""]))
        elif event.get("kind") == "invalid_event":
            entries.append((str(event.get("timestamp", "")), 2, [f"**The runtime sent an event GridLens could not read** at {_local_time(event.get('timestamp'))}:", "", _block(str(event.get("text", ""))), ""]))
    for run in _read_lines(directory, "script_executions.jsonl", notes):
        if run.get("phase") != "completed":
            continue
        lines = [f"### You ran proposed script {run.get('proposal_id', '?')} ({run.get('status', '?')}, exit code {run.get('exit_code')})", ""]
        if run.get("detail"):
            lines += [str(run["detail"]), ""]
        lines += ["Output (unverified by GridLens):", "", _block(str(run.get("output_excerpt", ""))), ""]
        entries.append((str(run.get("approved_at", "")), 1, lines))
    entries.sort(key=lambda entry: (entry[0], entry[1]))
    return entries


def render_conversation_log(directory: Path) -> str:
    """Return the Markdown record of the conversation in directory."""
    notes: list[str] = []
    entries = _entries(directory, notes)
    lines = _header(directory, notes)
    if not entries:
        lines.append("No messages yet.")
    for _, _, block in entries:
        lines.extend(block)
    return "\n".join(lines).rstrip() + "\n"


def write_conversation_log(directory: Path) -> Path:
    """Write conversation.md into the session folder in one step, at mode 0600, and return its path."""
    path = scoped_path(directory, CONVERSATION_LOG)
    temporary = scoped_path(directory, CONVERSATION_LOG + ".tmp")
    text = render_conversation_log(directory)
    temporary.unlink(missing_ok=True)
    with files.open_private(temporary, "x") as handle:
        handle.write(text)
    files.replace(temporary, path)
    return path
