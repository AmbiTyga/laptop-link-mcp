"""Subprocess fixture for exercising the official MCP protocol without Bluetooth."""
import asyncio
import sys
from pathlib import Path

from conftest import MemoryTransport
from mcp.server.stdio import stdio_server

from laptop_link_mcp.tools import create_server
from laptop_link_mcp.request_store import Journal
from laptop_link_mcp.session import Remote


async def main():
    journal = Journal(Path(sys.argv[1]), "test-device")
    try:
        server = create_server(Remote(MemoryTransport(), journal))
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        journal.close()


asyncio.run(main())
