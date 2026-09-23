"""The shared machinery behind every GridLens agent tool.

`tool` marks a method as a tool, and `ToolBase._invoke` runs it: it assigns the call ID, binds and checks
the arguments, turns exceptions into stable error codes, bounds the result, records the files the call
read, and writes the paired started and completed audit records. The tool modules subclass `ToolBase`
and contain only the behavior of their tools.
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
from gridlens.agent.session import SessionContext, find_project, read_json, resolve_run, safe_utf8, scoped_path, timestamp
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION
from gridlens.analysis.parser_models import PARSER_VERSION


MAX_ROWS = 50
MAX_RESULT_BYTES = 16 * 1024
MAX_TABLE_ROWS = 250_000
MAX_AUDIT_BYTES = 32 * 1024 * 1024
MAX_ARGUMENT_BYTES = 4096
# A proposed script travels in its arguments, so that one tool gets a larger allowance.
MAX_SCRIPT_ARGUMENT_BYTES = 32 * 1024
OVERSIZE_SOURCE_LIMIT = 20
OVERSIZE_WARNING_LIMIT = 10
METRIC_VERSION = "2026.09.21"


def _bounded_strings(value: object) -> object:
    """Cap and sanitize model-visible strings and audit keys from untrusted artifacts."""
    if isinstance(value, str):
        return safe_utf8(value)[:1024]
    if isinstance(value, list):
        return [_bounded_strings(item) for item in value[:MAX_TABLE_ROWS]]
    if isinstance(value, dict):
        return {str(safe_utf8(key))[:128]: _bounded_strings(item) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


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


def _fit_to_budget(result: dict) -> dict:
    """Drop rows until the serialized result fits, and report the truncation honestly.

    A result that cannot fit even with no rows is replaced by an error, because a silently emptied
    envelope would read to the model as a run with nothing in it.
    """
    while len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT_BYTES and result["data"]["rows"]:
        result["data"]["rows"].pop()
        result["data"]["truncated"] = True
        if "byte_limit" not in result["data"]["truncation_reasons"]:
            result["data"]["truncation_reasons"].append("byte_limit")
    result["data"]["returned"] = len(result["data"]["rows"])
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
        result["data"] = {"rows": [], "returned": 0, "total_matching": 0, "truncated": True, "truncation_reasons": ["byte_limit"]}
        result["error"] = {"code": "RESULT_TOO_LARGE", "remedy": "Narrow the request to a single run or facility."}
        result["provenance"]["sources"] = result["provenance"]["sources"][:OVERSIZE_SOURCE_LIMIT]
        result["warnings"] = result["warnings"][:OVERSIZE_WARNING_LIMIT]
    return result


def tool(method):
    """Keep typed tool signatures while centralizing limits and append-only auditing."""
    @wraps(method)
    def audited(self, *args, **kwargs):
        return self._invoke(method, args, kwargs)
    return audited


class ToolBase:
    """The per-call machinery shared by every tool module, bound to one session.

    Instances are cheap and short-lived. `sources` and `warnings` accumulate during a single call
    and are reset by `_invoke`, so they belong to the call in flight rather than to the session."""
    def __init__(self, context: SessionContext) -> None:
        self.context = context
        self.sources: dict[str, dict] = {}
        self.warnings: list[str] = []

    def _invoke(self, method, args: tuple, kwargs: dict) -> dict:
        """Call one tool with bounds and stable errors, then pair its started audit with completion."""
        audit = scoped_path(self.context.directory, "tool_calls.jsonl")
        with os.fdopen(os.open(audit, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600), "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if os.fstat(handle.fileno()).st_size > MAX_AUDIT_BYTES:
                raise AgentError("SESSION_LIMIT", "Start a new session; the tool audit has reached its size limit.")
            handle.seek(0)
            count = sum(1 for line in handle if '"phase": "started"' in line)
            call_id = f"T{count + 1}"
            started = timestamp()
            self.sources, self.warnings = {}, []
            arguments = {}
            result = _empty_result(call_id)
            arguments = _bind_arguments(method, self, args, kwargs)
            limit_info = {"requested_limit": arguments["limit"], "max_rows_per_call": MAX_ROWS} if "limit" in arguments else {}
            result["data"].update(limit_info)
            handle.write(json.dumps({"call_id": call_id, "phase": "started", "tool": method.__name__, "arguments": _bounded_strings(arguments), "started_at": started}, allow_nan=False) + "\n")
            handle.flush()
            try:
                try:
                    if arguments.get("invalid_arguments"):
                        raise ValueError
                    if len(json.dumps(arguments, allow_nan=False).encode()) > (MAX_SCRIPT_ARGUMENT_BYTES if method.__name__ == "propose_analysis_script" else MAX_ARGUMENT_BYTES):
                        raise ValueError
                    if "limit" in arguments and (isinstance(arguments["limit"], bool) or not isinstance(arguments["limit"], int) or arguments["limit"] < 1):
                        raise ValueError
                    if "limit" in arguments and arguments["limit"] > MAX_ROWS:
                        raise AgentError("LIMIT_EXCEEDS_CAP", f"Use a limit of at most {MAX_ROWS} rows. For whole-run means, use summarize_loading; the agent cannot return every row of a large result.")
                    data = method(self, *args, **kwargs)
                    rows = data.pop("rows", [])
                    total = data.pop("total_matching", len(rows))
                    limit = min(MAX_ROWS, max(1, int(arguments.get("limit", MAX_ROWS))))
                    result["data"] = {**data, **limit_info, "rows": rows[:limit], "returned": min(len(rows), limit), "total_matching": total, "truncated": total > limit, "truncation_reasons": ["row_limit"] if total > limit else []}
                except AgentError as exc:
                    result["error"] = {"code": exc.code, "remedy": str(exc)}
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
                    result = _fit_to_budget(_bounded_strings(result))
                    completed = {
                        "call_id": call_id, "phase": "completed", "tool": method.__name__,
                        "arguments": _bounded_strings(arguments), "started_at": started, "ended_at": timestamp(),
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
