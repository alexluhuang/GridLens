"""Time and token accounting per turn, computed from a session's audit files."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gridlens.agent import accounting
from gridlens.agent.conversation_log import render_conversation_log
from gridlens.agent.session import SessionContext


def write_lines(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


@pytest.fixture
def session(tmp_path) -> Path:
    """Return a session with an answered turn that called two tools, a turn that failed, and one still running."""
    context = SessionContext.create(None, (), "fixture:model", "http://127.0.0.1:11434", projects_dir=tmp_path / "projects")
    directory = context.directory
    write_lines(directory / "transcript.jsonl", [
        {"timestamp": "2026-09-30T10:00:00.000+00:00", "role": "user", "text": "Run the study\nand rank the lines."},
        {"timestamp": "2026-09-30T10:03:12.500+00:00", "role": "assistant", "text": "Done [T1]."},
        {"timestamp": "2026-09-30T10:10:00.000+00:00", "role": "user", "text": "And the transformers?"},
        {"timestamp": "2026-09-30T10:20:00.000+00:00", "role": "user", "text": "Still there?"},
    ])
    write_lines(directory / "tool_calls.jsonl", [
        {"call_id": "T1", "phase": "started", "tool": "start_run", "started_at": "2026-09-30T10:00:05.000+00:00"},
        {"call_id": "T1", "phase": "completed", "tool": "start_run", "started_at": "2026-09-30T10:00:05.000+00:00", "ended_at": "2026-09-30T10:00:05.250+00:00"},
        {"call_id": "T2", "phase": "completed", "tool": "get_status", "started_at": "2026-09-30T10:00:10.000+00:00", "ended_at": "2026-09-30T10:02:10.000+00:00"},
        {"call_id": "T3", "phase": "completed", "tool": "get_status", "started_at": "2026-09-30T10:02:20.000+00:00", "ended_at": "2026-09-30T10:02:21.000+00:00"},
        {"call_id": "T4", "phase": "completed", "tool": "rank", "started_at": "2026-09-30T10:10:30.000+00:00", "ended_at": "2026-09-30T10:10:30.500+00:00"},
    ])
    write_lines(directory / "runtime_events.jsonl", [
        {"timestamp": "2026-09-30T10:03:12.400+00:00", "kind": "completed", "text": "Done", "data": {"usage": {"input": 5000, "output": 400, "total": 88400, "cache_read": 83000, "cache_write": 0}}},
        {"timestamp": "2026-09-30T10:12:00.000+00:00", "kind": "error", "text": "The model stopped.", "code": "RUNTIME_ERROR"},
    ])
    return directory


def test_each_turn_has_its_time_in_tools_and_in_the_model_and_its_tokens(session):
    first, failed, running = accounting.turn_accounting(session)
    assert (first["outcome"], first["seconds"], first["tool_calls"], first["tool_seconds"], first["model_seconds"]) == ("answered", 192.5, 3, 121.25, 71.25)
    assert first["tools"] == {"start_run": {"calls": 1, "seconds": 0.25}, "get_status": {"calls": 2, "seconds": 121.0}}
    assert first["tokens"] == {"input": 5000, "cache_read": 83000, "cache_write": 0, "output": 400, "prompt": 88000, "total": 88400}
    assert first["output_tokens_per_second"] == pytest.approx(5.6) and first["question"] == "Run the study and rank the lines."
    assert (failed["outcome"], failed["seconds"], failed["tool_calls"], failed["tokens"]) == ("error", 120.0, 1, None)
    assert (running["outcome"], running["seconds"], running["model_seconds"]) == ("unfinished", None, None)
    summed = accounting.totals([first, failed, running])
    assert (summed["turns"], summed["answered"], summed["seconds"], summed["median_seconds"], summed["tool_calls"]) == (3, 1, 312.5, 156.25, 4)
    assert summed["tokens"]["total"] == 88400


def test_times_and_turns_read_as_a_person_would_say_them(session):
    first = accounting.turn_accounting(session)[0]
    assert [accounting.duration(value) for value in (0.019, 4.24, 192.5, 7384)] == ["19 ms", "4.2 s", "3 min 12 s", "2 h 3 min"]
    assert accounting.summary(first) == "3 min 12 s · 88,400 tokens"
    assert accounting.sentence(first) == "This turn took 3 min 12 s, 2 min 1 s of it in 3 GridLens tool calls. The model read 88,000 prompt tokens (83,000 from its cache) and wrote 400."


def test_the_conversation_record_gives_each_answer_its_time_and_tokens(session):
    text = render_conversation_log(session)
    assert "- Time and tokens: 3 turns, 5 min 12 s (2 min 2 s in GridLens tools), 88,400 tokens" in text
    assert "*This turn took 3 min 12 s, 2 min 1 s of it in 3 GridLens tool calls." in text
    assert text.index("Done [T1].") < text.index("*This turn took 3 min 12 s")


def test_a_session_without_audit_files_has_no_turns(tmp_path):
    assert accounting.turn_accounting(tmp_path) == [] and accounting.totals([])["tokens"] is None


def test_the_process_card_keeps_its_summary_when_completed_again():
    from PySide6.QtWidgets import QApplication

    from gridlens.gui.agent_conversation import ProcessCard

    app = QApplication.instance() or QApplication([])
    card = ProcessCard()
    card.complete("3 min 12 s · 88,400 tokens")
    card.complete()
    assert card.toggle.text() == "Process · 0 tools · 3 min 12 s · 88,400 tokens"


def test_the_evaluation_report_gets_accounting_from_sessions_it_did_not_record(session):
    path = Path(__file__).parents[1] / "scripts/render_agent_evaluation.py"
    spec = importlib.util.spec_from_file_location("render_agent_evaluation", path)
    render = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render)
    record = {"session": str(session), "turns": [{"id": "1", "seconds": 192.5}, {"id": "2", "seconds": 120.0}]}
    turns = render.with_accounting(record)["turns"]
    assert turns[0]["accounting"]["tokens"]["total"] == 88400 and turns[1]["accounting"]["outcome"] == "error"
    table = "\n".join(render.time_and_tokens(turns))
    assert "| Total time | 5 min 12 s |" in table and "| Prompt tokens read | 88,000, 83,000 of them from the cache |" in table
    assert "| Prompts without token counts | 1 |" in table
