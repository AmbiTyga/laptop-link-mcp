"""Serialize requests over one persistent native CoreBluetooth subprocess."""
import asyncio
import json
from contextlib import suppress


class BridgeTransport:
    def __init__(self, command: list[str], timeout: float = 120):
        self.command = command
        self.timeout = timeout
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()

    async def exchange(self, request: dict) -> dict:
        data = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode()
        if len(data) > 131_072:
            raise ValueError("Encoded request exceeds 128 KiB")
        async with self.lock:
            try:
                async with asyncio.timeout(self.timeout + 5):
                    if self.process is None or self.process.returncode is not None:
                        await self.close()
                        self.process = await asyncio.create_subprocess_exec(
                            *self.command, stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE, stderr=None, limit=262_144,
                        )
                    process = self.process
                    process.stdin.write(data + b"\n")
                    await process.stdin.drain()
                    line = await process.stdout.readline()
                    if not line:
                        raise ConnectionError("BLE bridge disconnected; see host stderr for details")
                    response = json.loads(line)
                    if (response.get("version") != 1 or response.get("id") != request["id"]
                            or not isinstance(response.get("bootID"), str)
                            or (("result" in response) == ("error" in response))):
                        raise ConnectionError("Invalid BLE response envelope")
                    return response
            except BaseException:
                # Never leave a cancelled read or a late response on a reusable stream.
                await self.close()
                raise

    async def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
