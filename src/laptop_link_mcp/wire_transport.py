"""Select the BLE format using an authenticated, read-only legacy capability probe."""
import asyncio
import uuid

from .bridge import BridgeTransport


class WireTransport:
    def __init__(self, command: list[str], timeout: float = 120, mode: str = "auto", factory=BridgeTransport):
        if mode not in {"auto", "protobuf", "json"}:
            raise ValueError("Wire mode must be auto, protobuf, or json")
        self.command = command
        self.timeout = timeout
        self.mode = mode
        self.selected: str | None = None if mode == "auto" else mode
        self.factory = factory
        self.transport = self._bridge(self.selected or "json")
        self.lock = asyncio.Lock()

    def _bridge(self, wire):
        return self.factory([*self.command, "--wire", wire], self.timeout)

    @property
    def process(self):
        return self.transport.process

    async def exchange(self, request: dict) -> dict:
        async with self.lock:
            try:
                response = None
                if self.selected is None:
                    probe = {"version": 1, "id": str(uuid.uuid4()), "method": "server.info", "params": {}}
                    if request["method"] == "server.info":
                        probe = request
                    capabilities = await self.transport.exchange(probe)
                    if capabilities.get("error"):
                        raise ConnectionError("Authenticated capability query failed")
                    formats = capabilities.get("result", {}).get("wire_formats", [])
                    self.selected = "protobuf" if "protobuf" in formats else "json"
                    if self.selected == "protobuf":
                        await self.transport.close()
                        self.transport = self._bridge("protobuf")
                    elif probe is request:
                        response = capabilities
                if response is None:
                    response = await self.transport.exchange(request)
                if request["method"] == "server.info":
                    response = {**response, "transport": {"wire_format": self.selected, "selection": self.mode}}
                return response
            except BaseException:
                await self.transport.close()
                raise

    async def close(self):
        await self.transport.close()
