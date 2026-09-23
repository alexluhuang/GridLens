from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gridlens.agent.tools import DESTRUCTIVE_TOOL_NAMES, TOOL_NAMES, WRITE_TOOL_NAMES


SOURCE_ROOT = str(Path(__file__).resolve().parents[1] / "src")
# GRIDLENS_TEST_MCP_EXECUTABLE points this module at the frozen GridLens binary, so the packaged entry
# point is exercised by the same assertions as the source one.
FROZEN = os.environ.get("GRIDLENS_TEST_MCP_EXECUTABLE", "")


def entry_point(*arguments: str) -> list[str]:
    return [FROZEN, *arguments] if FROZEN else [sys.executable, "-m", "gridlens", *arguments]


def entry_environment(context: Path | None) -> dict[str, str]:
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": SOURCE_ROOT}
    if context is not None:
        environment["GRIDLENS_AGENT_CONTEXT"] = str(context)
    return environment


def test_official_sdk_client_tools_and_scope(agent_context):
    async def exercise():
        argv = entry_point("--mcp-server")
        params = StdioServerParameters(
            command=argv[0], args=argv[1:],
            env=entry_environment(agent_context.directory / "context.json"),
        )
        async with stdio_client(params) as streams, ClientSession(*streams) as client:
            await client.initialize()
            listing = await client.list_tools()
            assert {tool.name for tool in listing.tools} == set(TOOL_NAMES)
            assert all(tool.annotations.readOnlyHint == (tool.name not in WRITE_TOOL_NAMES) for tool in listing.tools)
            assert {tool.name for tool in listing.tools if tool.annotations.destructiveHint} == set(DESTRUCTIVE_TOOL_NAMES)
            ranking = next(tool for tool in listing.tools if tool.name == "rank_branch_loading")
            assert "metric" in ranking.inputSchema["properties"]
            response = await client.call_tool("rank_branch_loading", {"run_id": "run_a", "limit": 1})
            assert not response.isError
            result = json.loads(response.content[0].text)
            assert result["data"]["rows"][0]["max_utilization_pct"] == 120
            # Compact JSON: pretty-printing would cost tokens and push results past runtime spill limits.
            assert "\n" not in response.content[0].text and response.structuredContent is None
            grouping = next(tool for tool in listing.tools if tool.name == "rank_groups")
            assert {"group", "object", "order", "metric", "statistic", "magnitude", "filters"} <= set(grouping.inputSchema["properties"])
            qualified = {"run_id": "run_a", "group": "control_area", "statistic": "count", "filters": [{"column": "max_utilization_pct", "op": ">", "value": 100}]}
            counted = json.loads((await client.call_tool("rank_groups", qualified)).content[0].text)
            assert [(row["group"], row["value"]) for row in counted["data"]["rows"]] == [("North", 2), ("South", 2)]
            # The schema names the qualifier columns, so an unknown one is refused before the tool runs.
            unknown_column = await client.call_tool("rank", {"run_id": "run_a", "filters": [{"column": "zone", "op": "==", "value": 1}]})
            assert unknown_column.isError
            rejected = await client.call_tool("get_run_method", {"run_id": "../outside"})
            assert json.loads(rejected.content[0].text)["error"]["code"] == "INVALID_RUN_ID"
    asyncio.run(exercise())


def test_mcp_server_fails_closed_without_a_session_context():
    # stdout purity matters: stdio is the MCP transport, so a diagnostic there would corrupt the protocol.
    completed = subprocess.run(entry_point("--mcp-server"), env=entry_environment(None), capture_output=True, text=True, timeout=60)
    assert completed.returncode == 2
    assert "INVALID_SESSION" in completed.stderr
    assert completed.stdout == ""


def test_agent_tool_cli_contract(agent_context):
    context = agent_context.directory / "context.json"

    def run(*arguments: str) -> subprocess.CompletedProcess:
        # Always a child process: argparse exits the interpreter on a rejected tool name or context.
        return subprocess.run(entry_point("--agent-tool", *arguments), env=entry_environment(None), capture_output=True, text=True, timeout=120)

    completed = run(str(context), "get_run_inventory")
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["error"] is None
    completed = run(str(context), "get_run_method", "--arguments", json.dumps({"run_id": "../x"}))
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["error"]["code"] == "INVALID_RUN_ID"
    # An unexpected argument is a tool-envelope error (exit 1), not a usage error (exit 2).
    completed = run(str(context), "get_run_inventory", "--arguments", json.dumps({"bogus": 1}))
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["error"]["code"] == "INVALID_DATA_OR_ARGUMENT"
    for arguments in ("[]", "{not json"):
        completed = run(str(context), "get_run_inventory", "--arguments", arguments)
        assert completed.returncode == 2
        assert completed.stdout == ""
    completed = run(str(context), "get_run_inventory", "--arguments", "[]")
    assert "Arguments must be a JSON object." in completed.stderr
    completed = run(str(context), "no_such_tool")
    assert completed.returncode == 2
    assert completed.stdout == ""
    completed = run(str(agent_context.project_root / "missing.json"), "get_run_inventory")
    assert completed.returncode == 2
    assert "INVALID_SESSION" in completed.stderr


@pytest.mark.parametrize("arguments", [("--agent-tool", "CONTEXT", "get_run_inventory"), ("--mcp-server",)])
def test_agent_entry_points_do_not_import_qt(agent_context, arguments):
    # -I keeps the child free of inherited PYTHON* settings; the source tree is put on the path explicitly
    # so the worktree, not an editable install elsewhere, is what runs.
    argv = [str(agent_context.directory / "context.json") if part == "CONTEXT" else part for part in arguments]
    code = (
        "import sys; sys.path.insert(0, " + repr(SOURCE_ROOT) + ");"
        "sys.argv = ['gridlens', *" + repr(argv) + "];"
        "from gridlens.main import main; main(); print('PySide6' in sys.modules)"
    )
    completed = subprocess.run([sys.executable, "-I", "-c", code], env=entry_environment(None), capture_output=True, text=True, timeout=120)
    assert completed.stdout.splitlines()[-1] == "False", completed.stderr
