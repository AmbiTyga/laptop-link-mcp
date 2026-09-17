import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_official_mcp_initialization_tools_errors_and_retry(tmp_path):
    params = StdioServerParameters(command=sys.executable,
                                  args=[str(Path(__file__).with_name("mcp_fixture.py")), str(tmp_path / "state")])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            hello = await session.initialize()
            assert hello.serverInfo.name == "laptop-link-mcp"
            tools = (await session.list_tools()).tools
            names = {t.name: t for t in tools}
            assert names["link_read_file"].annotations.readOnlyHint is True
            assert names["link_exec_start"].annotations.destructiveHint is True
            assert "link_download" in names and "link_retry" in names
            invalid = await session.call_tool("link_exec_start", {"shell": "hi", "timeout_seconds": -1})
            assert invalid.isError
            assert invalid.structuredContent["code"] == "local_error"
            status = await session.call_tool("link_status", {})
            assert status.structuredContent["result"]["root"] == "/remote/workspace"
            start = await session.call_tool("link_exec_start", {"shell": "echo once"})
            assert not start.isError
            retry = await session.call_tool("link_retry", {"request_id": start.structuredContent["id"]})
            assert retry.structuredContent == start.structuredContent
