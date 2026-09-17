#!/usr/bin/env python3
"""Exercise the real stdio MCP endpoint with read-only remote system commands."""
import argparse
import asyncio
import base64
import json
import time
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def inspect(key: str, state_dir: str | None):
    root = Path(__file__).resolve().parent.parent
    args = ["--key", str(Path(key).expanduser().absolute())]
    if state_dir:
        args += ["--state-dir", str(Path(state_dir).expanduser().absolute())]
    parameters = StdioServerParameters(command=str(root / "scripts/run.sh"), args=args)
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=150)) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"MCP initialized: {len(tools.tools)} tools", flush=True)

            async def call(name, arguments):
                reply = await session.call_tool(name, arguments)
                value = reply.structuredContent or json.loads(reply.content[0].text)
                if reply.isError:
                    raise RuntimeError(json.dumps(value))
                return value

            status = await call("link_status", {})
            print(json.dumps({"connection": status}, indent=2), flush=True)
            command = "/usr/bin/sw_vers; /usr/bin/uname -m; /usr/sbin/sysctl hw.model hw.memsize hw.ncpu"
            started = await call("link_exec_start", {"shell": command, "timeout_seconds": 15})
            job = started["result"]["job_id"]
            print(json.dumps({"job_id": job, "request_id": started["id"]}), flush=True)
            offsets = {"stdout": 0, "stderr": 0}
            output = {"stdout": bytearray(), "stderr": bytearray()}
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                response = await call("link_exec_poll", {"job_id": job, "stdout_offset": offsets["stdout"],
                                                       "stderr_offset": offsets["stderr"]})
                result = response["result"]
                for stream in output:
                    output[stream].extend(base64.b64decode(result[stream]["data"], validate=True))
                    offsets[stream] = result[stream]["next_offset"]
                if result["state"] != "running" and all(
                        offsets[s] == result[s]["retained_bytes"] for s in output):
                    print(json.dumps({"state": result["state"], "exit_code": result["exit_code"],
                                      "stdout": output["stdout"].decode("utf-8", errors="replace"),
                                      "stderr": output["stderr"].decode("utf-8", errors="replace")}, indent=2))
                    if result["state"] != "exited" or result["exit_code"] != 0:
                        raise RuntimeError("Remote inspection command did not exit successfully")
                    return
                await asyncio.sleep(0.5)
            raise TimeoutError(f"Output polling exceeded deadline; remote job {job} has its own timeout")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True)
    parser.add_argument("--state-dir")
    options = parser.parse_args()
    asyncio.run(inspect(options.key, options.state_dir))
