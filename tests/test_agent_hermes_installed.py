"""Opt-in compatibility/evaluation tests; all model prompts use synthetic data."""
from __future__ import annotations

import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import time
import tracemalloc

import pytest

from gridlens.agent.controller import AgentController, group_mean_source, session_sources
from gridlens.agent.hermes import HermesAdapter, SYSTEM_PROMPT
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import TOOL_NAMES, ToolService


PLAN_TARGET_MODELS = ("nemotron3:33b", "gemma4:31b")


def line_ranking(row: dict, metric: str) -> bool:
    """Return whether an audited call ranked facilities by metric with rank."""
    return row["outcome"] == "ok" and row["tool"] == "rank" and row.get("arguments", {}).get("metric") == metric


@pytest.mark.skipif(os.environ.get("GRIDLENS_TEST_HERMES") != "1", reason="Set GRIDLENS_TEST_HERMES=1 to exercise the installed Hermes CLI against a synthetic loopback API.")
def test_installed_hermes_exposes_only_gridlens_tools_and_resumes(agent_project):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data):
            raw = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/api/version":
                self.respond({"version": "0.0.0-test"})
            elif self.path == "/api/tags":
                self.respond({"models": [{"name": "synthetic:model"}]})
            else:
                self.respond({"object": "list", "data": [{"id": "synthetic:model", "object": "model"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/show":
                self.respond({"capabilities": ["completion", "tools"], "model_info": {"general.architecture": "llama", "llama.context_length": 65536}})
                return
            requests.append(body)
            has_result = any(message.get("role") == "tool" for message in body.get("messages", []))
            call = {"id": "synthetic_call", "type": "function", "function": {"name": "mcp__gridlens__rank", "arguments": '{"run_id":"run_a","magnitude":1}'}}
            message = {"role": "assistant", "content": "The maximum observed loading is 120% [T1]." if has_result else None}
            if not has_result:
                message["tool_calls"] = [call]
            reason = "stop" if has_result else "tool_calls"
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                delta = {**message}
                if "tool_calls" in delta:
                    delta["tool_calls"] = [{"index": 0, **call}]
                for content, finish in ((delta, None), ({}, reason)):
                    item = {"id": "test-completion", "object": "chat.completion.chunk", "created": int(time.time()), "model": "synthetic:model", "choices": [{"index": 0, "delta": content, "finish_reason": finish}]}
                    self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                self.respond({"id": "test-completion", "object": "chat.completion", "created": int(time.time()), "model": "synthetic:model", "choices": [{"index": 0, "message": message, "finish_reason": reason}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    context = SessionContext.create(agent_project, ("run_a",), "synthetic:model", endpoint)
    controller = AgentController(context, HermesAdapter(endpoint), timeout=60)
    try:
        answer = controller.run_turn("Which line is most congested?", lambda event: None)
        assert "120%" in answer
        assert session_sources(context.directory)[0]["tool"] == "rank"
        first_id = controller.continuation
        assert first_id
        messages = [json.loads(line) for line in (context.directory / "transcript.jsonl").read_text().splitlines()]
        events = [json.loads(line) for line in (context.directory / "runtime_events.jsonl").read_text().splitlines()]
        resumed = AgentController(SessionContext.load(context.directory / "context.json"), HermesAdapter(endpoint), timeout=60)
        resumed.restore(messages, events)
        assert resumed.continuation == first_id
        assert "120%" in resumed.run_turn("Repeat the result and cite it.", lambda event: None)
        tools_sent = [body["tools"] for body in requests if body.get("tools")]
        assert tools_sent
        expected = {"mcp__gridlens__" + name for name in TOOL_NAMES}
        assert all({item["function"]["name"] for item in listing} == expected for listing in tools_sent)
        assert any(SYSTEM_PROMPT.strip() in json.dumps(body, ensure_ascii=False).replace("\\n", "\n") for body in requests)
        print(f"\nHermes isolation + continuation passed: {context.directory}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.skipif(os.environ.get("GRIDLENS_TEST_LOCAL_MODELS") != "1", reason="Set GRIDLENS_TEST_LOCAL_MODELS=1 for installed Ollama model evaluation.")
def test_installed_local_models_share_tools_and_prompt(agent_project):
    """Use the synthetic project to score installed models; pytest reads scores and writes a JSON report."""
    adapter = HermesAdapter()
    status = adapter.probe()
    assert status.ready, status.message
    records = []
    selected = os.environ.get("GRIDLENS_TEST_MODEL_NAMES", "").split(",") if os.environ.get("GRIDLENS_TEST_MODEL_NAMES") else [model for model in PLAN_TARGET_MODELS if model in status.models]
    if not selected:
        pytest.skip("None of the plan target models is installed; set GRIDLENS_TEST_MODEL_NAMES to choose installed models.")
    assert set(selected).issubset(status.models)
    for model in selected:
        context = SessionContext.create(agent_project, ("run_a",), model, status.endpoint)
        controller = AgentController(context, HermesAdapter(status.endpoint))
        started = time.monotonic()
        answer = controller.run_turn("In run_a, which non-transformer line is most congested, and how confident should I be in that number?", lambda event: None)
        sources = session_sources(context.directory)
        ranked = [row for row in sources if line_ranking(row, "max_utilization_pct")]
        first = {
            "tool_selection": bool(ranked),
            "arguments": any(row["arguments"].get("run_id") == "run_a" and row["arguments"].get("object") == "branches" for row in ranked),
            "numeric_fidelity": bool(re.search(r"\b120(?:\.0+)?\s*%", answer)),
            "units": "%" in answer or "percent" in answer.casefold(),
            "metric_wording": bool(re.search(r"(maximum|highest|worst).{0,35}(observed|loading|utilization)", answer, re.I)),
            "convergence_caveat": bool(re.search(r"(non.converged|base.case|failed|not.*N.1)", answer, re.I)),
            "citation": any(f"[{row['call_id']}]" in answer for row in sources) and "invalid source" not in answer,
            "truncation_disclosure": not any(row["result"]["data"].get("truncated") for row in sources) or "truncat" in answer.lower() or "partial" in answer.lower(),
        }
        margin_context = SessionContext.create(agent_project, ("run_a",), model, status.endpoint)
        margin_answer = AgentController(margin_context, HermesAdapter(status.endpoint)).run_turn("In run_a, where is the largest thermal loading margin among non-transformer lines? State what the margin can and cannot establish.", lambda event: None)
        margin_sources = session_sources(margin_context.directory)
        margin = {
            "tool_selection": any(line_ranking(row, "thermal_margin_pct_points") for row in margin_sources),
            "numeric_fidelity": bool(re.search(r"\b20(?:\.0+)?\s*(?:percentage points?|%)", margin_answer, re.I)),
            "thermal_margin_wording": "margin" in margin_answer.lower() and ("percentage point" in margin_answer.lower() or "%" in margin_answer),
        }
        # A session names only a starting run; the agent may still compare it with any other run of the project.
        focused = SessionContext.create(agent_project, ("run_a",), model, status.endpoint)
        cross_answer = AgentController(focused, HermesAdapter(status.endpoint)).run_turn("Compare maximum line loading between run_a and run_b.", lambda event: None)
        cross_calls = session_sources(focused.directory)
        cross_run = {
            "compared": any(row["tool"] == "compare_runs" and row["outcome"] == "ok" for row in cross_calls),
            "numeric_fidelity": bool(re.search(r"\b10(?:\.0+)?\s*(?:percentage points?|%)", cross_answer, re.I)),
        }
        manifest = agent_project / "runs/run_a/reports/interactive_analysis_manifest.json"
        saved_manifest = manifest.read_text()
        try:
            damaged = json.loads(saved_manifest)
            damaged["dataset_version"] = "stale-evaluation-fixture"
            manifest.write_text(json.dumps(damaged))
            stale = SessionContext.create(agent_project, ("run_a",), model, status.endpoint)
            stale_answer = AgentController(stale, HermesAdapter(status.endpoint)).run_turn("What is the most congested line in run_a?", lambda event: None)
            stale_calls = session_sources(stale.directory)
            missing = {
                "tool_error_observed": any(row["result"]["error"] and row["result"]["error"]["code"] == "ANALYSIS_NOT_BUILT" for row in stale_calls),
                "no_invented_loading": not bool(re.search(r"\d+(?:\.\d+)?\s*%", stale_answer)),
                "rebuild_instruction": "build" in stale_answer.lower() or "refresh" in stale_answer.lower(),
            }
        finally:
            manifest.write_text(saved_manifest)
        record = {
            "model": model, "seconds": round(time.monotonic() - started, 3), "session": str(context.directory), "margin_session": str(margin_context.directory),
            "congestion": first, "margin": margin, "cross_run": cross_run, "missing_cache": missing,
            "score": sum(sum(values.values()) for values in (first, margin, cross_run, missing)),
            "possible": sum(len(values) for values in (first, margin, cross_run, missing)),
        }
        records.append(record)
        print(json.dumps(record))
    output = Path(os.environ.get("GRIDLENS_TEST_EVAL_OUTPUT", str(agent_project / "model_evaluation.json")))
    output.write_text(json.dumps(records, indent=2))
    assert all(
        record["congestion"]["tool_selection"] and record["congestion"]["numeric_fidelity"] and record["congestion"]["citation"]
        and record["cross_run"]["compared"] and record["missing_cache"]["no_invented_loading"]
        and record["missing_cache"]["rebuild_instruction"]
        for record in records
    ), records


@pytest.mark.skipif(os.environ.get("GRIDLENS_TEST_LOCAL_MODELS") != "1", reason="Set GRIDLENS_TEST_LOCAL_MODELS=1 for installed Ollama model evaluation.")
def test_installed_local_models_use_complete_voltage_groups(agent_project):
    """Use an 11-line fixture to check each installed model chooses the full-group tool and answer."""
    run = agent_project / "runs/run_a"
    for name in ("pflow_mm", "branch_metadata"):
        path = run / "reports/interactive_tables" / f"{name}.csv"
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        template = rows[0]
        for index in range(8):
            kv, maximum = (69, 40) if index < 4 else (400, 60)
            rows.append({**template, "line_id": f"extra-{index}", "section": "", "from_base_kv": kv, "to_base_kv": kv, "max_utilization_pct": maximum})
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(template))
            writer.writeheader()
            writer.writerows(rows)
    manifest = run / "reports/interactive_analysis_manifest.json"
    manifest.write_text(manifest.read_text())
    adapter = HermesAdapter()
    status = adapter.probe()
    assert status.ready, status.message
    selected = os.environ.get("GRIDLENS_TEST_MODEL_NAMES", "").split(",") if os.environ.get("GRIDLENS_TEST_MODEL_NAMES") else [model for model in PLAN_TARGET_MODELS if model in status.models]
    if not selected:
        pytest.skip("Neither target model is installed; set GRIDLENS_TEST_MODEL_NAMES to choose installed models.")
    assert set(selected).issubset(status.models)
    records = []
    for model in selected:
        context = SessionContext.create(agent_project, ("run_a",), model, status.endpoint)
        events = []
        answer = AgentController(context, HermesAdapter(status.endpoint)).run_turn("In run_a, rank all voltage groups by mean maximum observed line utilization across all monitored lines. Include the percentage for each group.", events.append)
        summaries = [row for row in session_sources(context.directory) if group_mean_source(row, "voltage", "line")]
        repaired = any(event.kind == "tool_start" and event.text == "rank_groups (verified scope)" for event in events)
        final = summaries[-1]["result"]["data"] if summaries else {}
        correct = bool(summaries and final.get("objects_used") == 11 and not final.get("truncated"))
        record = {"model": model, "summary_tool": bool(summaries), "model_selected_correct_scope": bool(correct and not repaired), "controller_repaired_scope": repaired, "full_population": correct, "answer": answer}
        records.append(record)
        print(json.dumps(record))
    output = Path(os.environ.get("GRIDLENS_TEST_GROUP_EVAL_OUTPUT", str(agent_project / "voltage_group_evaluation.json")))
    output.write_text(json.dumps(records, indent=2))
    assert all(record["summary_tool"] and record["full_population"] and all(value in record["answer"] for value in ("103.3%", "60.0%", "40.0%", "all 11 matching facilities")) for record in records), records


@pytest.mark.skipif(not os.environ.get("GRIDLENS_TEST_SAMPLE_PROJECT"), reason="Set GRIDLENS_TEST_SAMPLE_PROJECT for a read-only cache benchmark.")
def test_sample_project_cache_benchmark(tmp_path):
    root = Path(os.environ["GRIDLENS_TEST_SAMPLE_PROJECT"]).resolve()
    run_id = os.environ["GRIDLENS_TEST_SAMPLE_RUN"]
    # Tool-only benchmark writes its audit to pytest's scratch directory, never to the supplied project.
    context = SessionContext(root, (run_id,), "no-model", "http://127.0.0.1:11434", tmp_path, "benchmark")
    service = ToolService(context)
    times = []
    tracemalloc.start()
    for _ in range(2):
        started = time.monotonic()
        result = service.rank(run_id)
        times.append(round(time.monotonic() - started, 3))
        assert result["error"] is None, result["error"]
        assert result["data"]["rows"]
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({"cache_query_seconds": times, "python_peak_bytes": peak, "matching_facilities": result["data"]["total_matching"], "flat_source_bytes": [source["size_bytes"] for source in result["provenance"]["sources"] if source["path"].endswith("_flat.csv")]}))
