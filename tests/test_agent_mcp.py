from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gridlens.agent.tools import TOOL_NAMES


def test_official_sdk_client_tools_and_scope(agent_context):
    async def exercise():
        params = StdioServerParameters(
            command=os.environ.get("GRIDLENS_TEST_MCP_EXECUTABLE", sys.executable),
            args=["--mcp-server"] if os.environ.get("GRIDLENS_TEST_MCP_EXECUTABLE") else ["-m", "gridlens", "--mcp-server"],
            env={"PATH": os.environ["PATH"], "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "GRIDLENS_AGENT_CONTEXT": str(agent_context.directory / "context.json")},
        )
        async with stdio_client(params) as streams, ClientSession(*streams) as client:
            await client.initialize()
            listing = await client.list_tools()
            assert {tool.name for tool in listing.tools} == set(TOOL_NAMES)
            assert all(tool.annotations.readOnlyHint for tool in listing.tools)
            ranking = next(tool for tool in listing.tools if tool.name == "rank_branch_loading")
            assert "metric" in ranking.inputSchema["properties"]
            response = await client.call_tool("rank_branch_loading", {"run_id": "run_a", "limit": 1})
            assert not response.isError
            result = json.loads(response.content[0].text)
            assert result["data"]["rows"][0]["max_utilization_pct"] == 120
            rejected = await client.call_tool("get_run_method", {"run_id": "../outside"})
            assert json.loads(rejected.content[0].text)["error"]["code"] == "RUN_NOT_SELECTED"
    asyncio.run(exercise())
