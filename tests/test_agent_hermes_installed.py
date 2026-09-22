"""Opt-in compatibility/evaluation tests; all model prompts use synthetic data."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
import tracemalloc

import pytest

from gridlens.agent.controller import AgentController, session_sources
from gridlens.agent.hermes import HermesAdapter, SYSTEM_PROMPT
from gridlens.agent.session import SessionContext
from gridlens.agent.tools import TOOL_NAMES, ToolService


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
            call = {"id": "synthetic_call", "type": "function", "function": {"name": "mcp__gridlens__rank_branch_loading", "arguments": '{"run_id":"run_a","limit":1}'}}
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
        assert session_sources(context.directory)[0]["tool"] == "rank_branch_loading"
        first_id = controller.continuation
        assert first_id
        assert "120%" in controller.run_turn("Repeat the result and cite it.", lambda event: None)
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
    adapter = HermesAdapter()
    status = adapter.probe()
    assert status.ready, status.message
    records = []
    for model in status.models:
        context = SessionContext.create(agent_project, ("run_a",), model, status.endpoint)
        controller = AgentController(context, HermesAdapter(status.endpoint))
        started = time.monotonic()
        answer = controller.run_turn("In run_a, use rank_branch_loading with limit 1 to identify the most congested non-transformer line. Give its maximum observed loading percentage, circuit/section, convergence caveat and source citation. Keep the answer under 100 words.", lambda event: None)
        sources = session_sources(context.directory)
        passed = any(row["tool"] == "rank_branch_loading" and row["outcome"] == "ok" for row in sources) and "120" in answer and any(f"[{row['call_id']}]" in answer for row in sources)
        record = {"model": model, "seconds": round(time.monotonic() - started, 3), "passed": passed, "session": str(context.directory)}
        records.append(record)
        print(json.dumps(record))
    (agent_project / "model_evaluation.json").write_text(json.dumps(records, indent=2))
    assert all(record["passed"] for record in records), records


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
        result = service.rank_branch_loading(run_id)
        times.append(round(time.monotonic() - started, 3))
        assert result["error"] is None, result["error"]
        assert result["data"]["rows"]
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({"cache_query_seconds": times, "python_peak_bytes": peak, "matching_facilities": result["data"]["total_matching"], "flat_source_bytes": [source["size_bytes"] for source in result["provenance"]["sources"] if source["path"].endswith("_flat.csv")]}))
