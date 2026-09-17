import base64
import json

from jsonschema import Draft202012Validator
from mcp import types
from mcp.server.lowlevel import Server

from .tool_catalog import CATALOG, SPECS
from .session import RemoteFailure
from .file_transfer import download, upload


def create_server(remote) -> Server:
    server = Server("laptop-link-mcp", version="0.1.0", instructions=(
        "These tools operate on an enrolled remote Mac over BLE. Call link_status to identify its root. "
        "Remote paths are distinct from host paths. A failed/cancelled MCP call may have executed remotely. "
        "Recover ambiguous mutations with link_pending_requests/link_retry. "
        "Poll commands to completion and drain both output streams."
    ))

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=s.name, description=s.description, inputSchema=s.schema,
                           annotations=types.ToolAnnotations(readOnlyHint=s.read_only,
                                                            destructiveHint=not s.read_only,
                                                            idempotentHint=s.read_only,
                                                            openWorldHint=True)) for s in SPECS]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        try:
            result = await dispatch(remote, name, arguments)
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result))],
                                        structuredContent=result)
        except RemoteFailure as exc:
            detail = exc.detail
        except (ValueError, OSError) as exc:
            detail = {"code": "local_error", "message": str(exc)}
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(detail))],
                                    structuredContent=detail, isError=True)

    return server


async def dispatch(remote, name: str, arguments: dict) -> dict:
    spec = CATALOG.get(name)
    if spec is None:
        raise ValueError("Unknown BLE tool")
    error = next(Draft202012Validator(spec.schema).iter_errors(arguments), None)
    if error:
        # Avoid echoing an entire invalid file or secret environment in SDK validation errors.
        location = ".".join(str(part) for part in error.absolute_path) or "arguments"
        raise ValueError(f"Invalid {location}: constraint {error.validator}")
    params = dict(arguments)
    if "text" in params:
        params["data"] = base64.b64encode(params.pop("text").encode("utf-8")).decode()
    if "data" in params:
        try:
            raw = base64.b64decode(params["data"], validate=True)
        except ValueError as exc:
            raise ValueError("Invalid base64 data") from exc
        if len(raw) > 65536 or (name == "link_upload_chunk" and not raw):
            raise ValueError("Data must be <=65536 bytes and upload chunks must be nonempty")
    if spec.method:
        return await remote.call(spec.method, params)
    if name == "link_retry":
        return await remote.retry(params["request_id"])
    if name == "link_pending_requests":
        return {"pending": remote.journal.pending()}
    if name == "link_upload":
        return await upload(remote, **params)
    if name == "link_download":
        return await download(remote, **params)
    raise ValueError("Tool has no implementation")
