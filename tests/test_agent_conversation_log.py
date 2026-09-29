"""The readable conversation record, and moving sessions out of the hidden folder of earlier versions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from gridlens.agent.conversation_log import MAX_RESULT_CHARS, write_conversation_log
from gridlens.agent.session import (
    LEGACY_WORKSPACE_SESSIONS, WORKSPACE_SESSIONS, SessionContext, append_event, export_session, migrate_legacy_sessions, saved_sessions,
)


def _record_turn(context: SessionContext) -> None:
    """Write one turn's audit files as the controller and the tool server would."""
    context.message("user", "Which lines are most loaded?")
    append_event(context.directory, "runtime_events.jsonl", {"kind": "tool_start", "text": "mcp__gridlens__rank", "data": {}})
    started = {"call_id": "T1", "phase": "started", "tool": "rank", "arguments": {"run_id": "run_a", "magnitude": 3}, "started_at": "2999-01-01T00:00:01.000+00:00"}
    completed = {
        **started, "phase": "completed", "ended_at": "2999-01-01T00:00:01.250+00:00", "outcome": "ok",
        "result": {"call_id": "T1", "data": {"rows": [{"object": "A to B (1)", "value": 120.0}], "note": "```not a fence end```"}, "error": None},
    }
    job = {"call_id": "T2", "phase": "completed", "tool": "run_analysis", "arguments": {"run_id": "run_a"}, "started_at": "2999-01-01T00:00:02.000+00:00", "ended_at": "2999-01-01T00:00:02.100+00:00", "outcome": "ok",
           "result": {"data": {"job_id": "29990101T000002Z_0123abcd", "rows": [{"job_id": "29990101T000002Z_0123abcd", "kind": "analysis", "project_root": "/p/Study"}]}}}
    failed = {"call_id": "T3", "phase": "completed", "tool": "read_file", "arguments": {"path": "x"}, "started_at": "2999-01-01T00:00:03.000+00:00", "ended_at": "2999-01-01T00:00:03.000+00:00", "outcome": "error",
              "result": {"data": {}, "error": {"code": "FILE_NOT_FOUND", "remedy": "Use list_files."}}}
    with (context.directory / "tool_calls.jsonl").open("w", encoding="utf-8") as handle:
        for row in (started, completed, job, failed):
            handle.write(json.dumps(row) + "\n")
    (context.directory / "transcript.jsonl").open("a").write(json.dumps({"timestamp": "2999-01-01T00:00:05.000+00:00", "role": "assistant", "text": "**A to B** is at 120% [T1]."}) + "\n")
    append_event(context.directory, "runtime_events.jsonl", {"kind": "error", "code": "CANCELLED", "text": "Turn stopped."})


def test_conversation_log_shows_messages_tool_calls_results_jobs_and_errors(agent_context):
    """conversation.md holds the whole conversation, in order, with each call's arguments and complete result."""
    _record_turn(agent_context)
    path = write_conversation_log(agent_context.directory)
    text = path.read_text()
    assert path == agent_context.directory / "conversation.md"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert text.startswith("# Clarke conversation")
    assert "- Model: fixture:model" in text and "`tool_calls.jsonl`" in text
    question, call, job, failure, answer = (text.index(item) for item in (
        "Which lines are most loaded?", "### Tool call T1: rank (ok, 250 ms)", "Started background job 29990101T000002Z_0123abcd",
        "Error FILE_NOT_FOUND: Use list_files.", "**A to B** is at 120% [T1].",
    ))
    assert question < call < job < failure < answer
    assert '"magnitude": 3' in text and '"object": "A to B (1)"' in text
    # Content with backticks sits inside a longer fence, so it cannot end its block.
    assert "````json" in text
    assert "**Error** (CANCELLED)" in text
    # Rewriting it gives the same file.
    assert write_conversation_log(agent_context.directory).read_text() == text


def test_conversation_log_cuts_only_huge_results_and_points_at_the_full_one(agent_context):
    """A result too long to read is cut in the log, which names where the complete one is."""
    agent_context.message("user", "All rows")
    row = {"call_id": "T1", "phase": "completed", "tool": "rank", "arguments": {}, "started_at": "2999-01-01T00:00:01+00:00", "ended_at": "2999-01-01T00:00:02+00:00", "outcome": "ok",
           "result": {"data": {"rows": ["x" * 100] * (MAX_RESULT_CHARS // 50), "rows_file": "/s/results/T1.csv"}}}
    (agent_context.directory / "tool_calls.jsonl").write_text(json.dumps(row) + "\n")
    text = write_conversation_log(agent_context.directory).read_text()
    assert "the complete result is in tool_calls.jsonl and /s/results/T1.csv" in text
    assert len(text) < MAX_RESULT_CHARS * 2


def test_export_includes_the_conversation_log(agent_context, tmp_path):
    """The exported archive carries the readable record with the audit files."""
    from zipfile import ZipFile

    _record_turn(agent_context)
    write_conversation_log(agent_context.directory)
    export_session(agent_context.directory, tmp_path / "audit.zip")
    assert "conversation.md" in ZipFile(tmp_path / "audit.zip").namelist()


def test_legacy_hidden_sessions_move_to_the_visible_folder(agent_project, tmp_path):
    """Sessions in the hidden folder move to Clarke conversations, open from there, and the hidden folder goes."""
    context = SessionContext.create(agent_project, ("run_a",), "fixture:model", "http://127.0.0.1:11434", projects_dir=tmp_path)
    context.message("user", "Hello")
    legacy_root = tmp_path / LEGACY_WORKSPACE_SESSIONS
    legacy_root.mkdir(parents=True)
    legacy = legacy_root / context.session_id
    os.rename(context.directory, legacy)
    record = json.loads((legacy / "context.json").read_text())
    (legacy / "context.json").write_text(json.dumps({**record, "directory": str(legacy)}))
    os.chmod(legacy / "context.json", 0o600)
    # Before the move the legacy folder is listed and opens.
    assert saved_sessions(tmp_path) == [legacy]
    assert SessionContext.load(legacy / "context.json").directory == legacy
    moved = migrate_legacy_sessions(tmp_path)
    target = tmp_path / WORKSPACE_SESSIONS / context.session_id
    assert moved == [target]
    assert not (tmp_path / ".gridlens-agent").exists()
    loaded = SessionContext.load(target / "context.json")
    assert (loaded.directory, loaded.run_ids) == (target.resolve(), ("run_a",))
    assert stat.S_IMODE((target / "context.json").stat().st_mode) == 0o600
    assert "Hello" in (target / "conversation.md").read_text()
    assert saved_sessions(tmp_path) == [target]
    assert migrate_legacy_sessions(tmp_path) == []


def test_a_legacy_session_that_cannot_move_stays_listed(tmp_path):
    """A name already taken in the visible folder leaves the legacy session where it is."""
    legacy = tmp_path / LEGACY_WORKSPACE_SESSIONS / "20260101T000000Z_aaaaaaaaaaaa"
    legacy.mkdir(parents=True)
    (legacy / "context.json").write_text("{}")
    (tmp_path / WORKSPACE_SESSIONS / legacy.name).mkdir(parents=True)
    assert migrate_legacy_sessions(tmp_path) == []
    assert legacy.is_dir()
    assert legacy in saved_sessions(tmp_path)
    assert migrate_legacy_sessions(Path(tmp_path / "missing")) == []
