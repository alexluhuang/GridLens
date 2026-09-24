"""The shared machinery behind every GridLens agent tool.

`tool` marks a method as a tool, and `ToolBase._invoke` runs it: it assigns the call ID, binds and checks
the arguments, turns exceptions into stable error codes, pages the rows, records the files the call read,
and writes the paired started and completed audit records. The tool modules subclass `ToolBase` and
contain only the behavior of their tools.

There is no maximum row count. `limit=0` returns every matching row and `offset` pages through them. What
is bounded is the copy sent inline to the model: a result larger than `MAX_INLINE_BYTES` is saved whole to
the session's `results/` folder, as `<call_id>.json` and its rows as `<call_id>.csv`, and the inline copy
keeps as many rows as fit plus the paths of those files. The model reads the files with its own file or
code tools, or pages with offset, so nothing a tool computed is lost.
"""
from __future__ import annotations

import csv
import fcntl
from functools import wraps
import inspect
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from gridlens.agent.policy import AgentError
from gridlens.agent.session import (
    SessionContext, find_project, read_json, resolve_run, safe_utf8, scoped_path, timestamp, write_json,
)
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.parser_models import PARSER_VERSION
from gridlens.core.validation import ValidationError


# Runtimes spill tool results of roughly 50,000 characters to their own files, measured after they embed
# the result in their own JSON, which escapes quotes and adds about a tenth. Staying below that keeps the
# complete copy in the GridLens session, where the audit can point to it.
MAX_INLINE_BYTES = 36_000
# Room kept inside MAX_INLINE_BYTES for the note that names the saved files.
NOTE_ALLOWANCE = 1024
MAX_STRING_CHARS = 8192
MAX_KEY_CHARS = 128
MAX_TABLE_ROWS = 250_000
MAX_AUDIT_BYTES = 256 * 1024 * 1024
MAX_ARGUMENT_BYTES = 64 * 1024
OVERSIZE_SOURCE_LIMIT = 20
OVERSIZE_WARNING_LIMIT = 10
METRIC_VERSION = "2026.09.21"
RESULTS_FOLDER = "results"
PAGE_FIELDS = ("returned", "total_matching", "offset", "limit", "truncated", "next_offset")


def _clean(value: object, max_chars: int | None = MAX_STRING_CHARS) -> object:
    """Return value ready for JSON: valid UTF-8, no NaN or infinity, bounded keys, and strings cut to max_chars.

    max_chars=None keeps strings whole, for the complete copy written to the results folder.
    """
    if isinstance(value, str):
        text = safe_utf8(value)
        return text if max_chars is None else text[:max_chars]
    if isinstance(value, (list, tuple)):
        return [_clean(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {str(safe_utf8(str(key)))[:MAX_KEY_CHARS]: _clean(item, max_chars) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _size(value: object) -> int:
    """Return the size in bytes of value serialized as JSON."""
    return len(json.dumps(value, ensure_ascii=False).encode())


def _empty_result(call_id: str) -> dict:
    """Build the result envelope every tool returns, successful or not."""
    return {
        "call_id": call_id,
        "data": {"rows": [], "returned": 0, "total_matching": 0, "truncated": False},
        "provenance": {
            "sources": [], "dataset_version": ANALYSIS_DATASET_VERSION,
            "parser_version": PARSER_VERSION, "metric_definition_version": METRIC_VERSION,
        },
        "warnings": [], "error": None,
    }


def _bind_arguments(method, service, args: tuple, kwargs: dict) -> dict:
    """Resolve the call's arguments for the audit, flagging a signature mismatch rather than raising.

    The audit records what the model asked for even when the request was malformed, so a rejected call
    still leaves a trace. `_invoke` turns the flag into the error the model sees.
    """
    try:
        bound = inspect.signature(method).bind(service, *args, **kwargs)
    except TypeError:
        return {"invalid_arguments": True}
    bound.apply_defaults()
    return {key: value for key, value in bound.arguments.items() if key != "self"}


def _check_arguments(arguments: dict) -> None:
    """Refuse malformed arguments, an oversized argument set, or a negative offset, limit, or magnitude."""
    if arguments.get("invalid_arguments"):
        raise ValueError("The arguments do not match the tool.")
    if _size(arguments) > MAX_ARGUMENT_BYTES:
        raise ValueError("The arguments are too large.")
    for name in ("offset", "limit", "magnitude"):
        value = arguments.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a whole number of at least 0.")


def page_result(page: list, total: int, offset: int, limit: int) -> dict:
    """Return a page of rows that starts at offset among total matching rows, with the fields that describe it."""
    end = offset + len(page)
    return {
        "rows": page, "returned": len(page), "total_matching": total, "offset": offset, "limit": limit,
        "truncated": end < total, "next_offset": end if end < total else None,
    }


def page_rows(rows: list, total: int, offset: int, limit: int) -> dict:
    """Cut one page from a list of rows and describe it.

    limit=0 means every row from offset on. total is the number of matching rows, which can exceed
    len(rows) when a tool already stopped collecting rows past the end of the page.
    """
    return page_result(rows[offset:] if limit == 0 else rows[offset:offset + limit], total, offset, limit)


def _csv_cell(value: object) -> object:
    """Return a value a CSV cell can hold, writing lists and objects as JSON text."""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value


def tool(method):
    """Mark a method as a tool: calls go through `ToolBase._invoke`, and the signature stays typed."""
    @wraps(method)
    def audited(self, *args, **kwargs):
        return self._invoke(method, args, kwargs)
    return audited


class ToolBase:
    """The per-call machinery shared by every tool module, bound to one session.

    Instances are cheap and short-lived. `call_id`, `sources`, and `warnings` belong to the call in
    flight and are reset by `_invoke`."""
    def __init__(self, context: SessionContext, *, confirm_changes: bool = False) -> None:
        """Bind the tools to a session. confirm_changes makes a destructive change wait for the user's
        confirmation in a later turn; the MCP server sets it, so every model is held to it, while a direct
        caller, such as a script or a test, acts at once, as a GUI button does."""
        self.context = context
        self.confirm_changes = confirm_changes
        self.call_id = ""
        self.sources: dict[str, dict] = {}
        self.warnings: list[str] = []

    def _invoke(self, method, args: tuple, kwargs: dict) -> dict:
        """Call one tool with stable errors and paged rows, then pair its started audit with completion.

        A tool returns its rows and, optionally, total_matching. `_invoke` then pages the rows by the
        call's offset and limit. A tool that pages its own rows, because it streams a file too large to
        hold, returns the page fields itself and is left as it is.
        """
        audit = scoped_path(self.context.directory, "tool_calls.jsonl")
        with os.fdopen(os.open(audit, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600), "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if os.fstat(handle.fileno()).st_size > MAX_AUDIT_BYTES:
                raise AgentError("SESSION_LIMIT", "Start a new session; the tool audit has reached its size limit.")
            handle.seek(0)
            count = sum(1 for line in handle if '"phase": "started"' in line)
            call_id = f"T{count + 1}"
            started = timestamp()
            self.call_id, self.sources, self.warnings = call_id, {}, []
            result = _empty_result(call_id)
            arguments = _bind_arguments(method, self, args, kwargs)
            handle.write(json.dumps({"call_id": call_id, "phase": "started", "tool": method.__name__, "arguments": _clean(arguments), "started_at": started}, allow_nan=False) + "\n")
            handle.flush()
            try:
                try:
                    _check_arguments(arguments)
                    data = method(self, *args, **kwargs)
                    if "offset" not in data:
                        rows = data.pop("rows", [])
                        total = data.pop("total_matching", len(rows))
                        data.update(page_rows(rows, total, arguments.get("offset", 0), arguments.get("limit", 0)))
                    result["data"] = data
                except AgentError as exc:
                    result["error"] = {"code": exc.code, "remedy": str(exc)}
                except ValidationError as exc:
                    # GridLens validation messages are written for the person who gave the value.
                    result["error"] = {"code": "INVALID_INPUT", "remedy": str(exc)}
                except (TypeError, ValueError, KeyError, AttributeError, csv.Error, ET.ParseError):
                    result["error"] = {"code": "INVALID_DATA_OR_ARGUMENT", "remedy": "Check the tool arguments and rebuild malformed analysis artifacts in GridLens."}
                except OSError:
                    result["error"] = {"code": "ARTIFACT_UNAVAILABLE", "remedy": "Check that the selected run and its analysis files are readable."}
                except Exception:
                    result["error"] = {"code": "INTERNAL_ERROR", "remedy": "The tool failed unexpectedly. Check the session audit and retry."}
                except BaseException:
                    result["error"] = {"code": "INTERNAL_ERROR", "remedy": "The tool was interrupted before completing."}
                    raise
            finally:
                try:
                    result["provenance"]["sources"] = list(self.sources.values())
                    result["warnings"] = list(dict.fromkeys(self.warnings))
                    result = self._fit_inline(result)
                    completed = {
                        "call_id": call_id, "phase": "completed", "tool": method.__name__,
                        "arguments": _clean(arguments), "started_at": started, "ended_at": timestamp(),
                        "outcome": "error" if result["error"] else "ok", "result": result,
                    }
                    line = json.dumps(completed, ensure_ascii=False, allow_nan=False)
                except Exception:
                    result = _empty_result(call_id)
                    result["error"] = {"code": "INTERNAL_ERROR", "remedy": "The tool failed unexpectedly. Check the session audit and retry."}
                    line = json.dumps({"call_id": call_id, "phase": "completed", "tool": method.__name__, "outcome": "error", "error": {"code": "INTERNAL_ERROR"}, "result": result}, ensure_ascii=True)
                handle.write(line + "\n")
                handle.flush()
            return result

    def _fit_inline(self, result: dict) -> dict:
        """Return the copy of result sent to the model, saving the complete result when it is too large.

        The inline copy keeps as many rows as fit in MAX_INLINE_BYTES, found by bisection, and names the
        files that hold everything. When even the page fields do not fit alongside the other data, the
        inline copy keeps only the page fields and the file paths.
        """
        inline = _clean(result)
        if _size(inline) <= MAX_INLINE_BYTES:
            return inline
        data = inline["data"]
        rows = data.get("rows") or []
        json_path, csv_path = self._save_complete_result(_clean(result, None))
        data.update(inline_rows=0, result_file=json_path, rows_file=csv_path)
        budget = MAX_INLINE_BYTES - NOTE_ALLOWANCE
        low, high = 0, len(rows)
        while low < high:
            middle = (low + high + 1) // 2
            data["rows"] = rows[:middle]
            if _size(inline) <= budget:
                low = middle
            else:
                high = middle - 1
        data["rows"], data["inline_rows"] = rows[:low], low
        if _size(inline) > budget:
            inline["data"] = {key: data.get(key) for key in PAGE_FIELDS} | {"rows": [], "inline_rows": 0, "result_file": json_path, "rows_file": csv_path}
            inline["provenance"]["sources"] = inline["provenance"]["sources"][:OVERSIZE_SOURCE_LIMIT]
            inline["warnings"] = inline["warnings"][:OVERSIZE_WARNING_LIMIT]
        shown = f"{inline['data']['inline_rows']:,} of {len(rows):,} rows are shown here" if rows else "the data is not shown here"
        saved = f" and its rows in {csv_path}" if csv_path else ""
        inline["warnings"].append(f"This result is too large to show whole, so {shown}. The complete result is in {json_path}{saved}. Read those files with your file or code tools, or page with offset and limit.")
        return inline

    def _save_complete_result(self, result: dict) -> tuple[str, str | None]:
        """Write a complete result to the session's results folder, and its rows as CSV when it has rows."""
        folder = scoped_path(self.context.directory, RESULTS_FOLDER, directory=True)
        folder.mkdir(mode=0o700, exist_ok=True)
        json_path = scoped_path(folder, f"{result['call_id']}.json")
        write_json(json_path, result)
        rows = [row for row in result["data"].get("rows") or [] if isinstance(row, dict)]
        if not rows:
            return str(json_path), None
        csv_path = scoped_path(folder, f"{result['call_id']}.csv")
        columns = list(dict.fromkeys(key for row in rows for key in row))
        with os.fdopen(os.open(csv_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_cell(value) for key, value in row.items()})
        return str(json_path), str(csv_path)

    def _source(self, path: Path, root: Path) -> Path:
        """Check that path stays inside root, record it as a source of this call, and return it.

        Sources are recorded as absolute paths, so the model can open the same file with its own tools.
        """
        path = scoped_path(root, path.relative_to(root))
        info = path.stat()
        self.sources[str(path)] = {"path": str(path), "size_bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
        return path

    def _project(self, project: str = "") -> Path:
        """Resolve a project argument to its folder; blank means the project open in the session."""
        text = str(project or "").strip()
        if not text:
            if self.context.project_root is None:
                raise AgentError("NO_PROJECT", "Name a project (list_projects shows them) or create one with create_project.")
            return self.context.project_root
        return find_project(text, self.context.projects_folder)

    def _run(self, run_id: str, project: str = "", *, completed: bool = True) -> Path:
        """Resolve a run of a project to its folder. The analysis tools need a completed run."""
        return resolve_run(self._project(project), run_id, completed=completed)

    def _json(self, run: Path, relative: str) -> dict:
        """Read a bounded JSON file inside run and record it as a source."""
        path = self._source(run / relative, run)
        return read_json(path)
