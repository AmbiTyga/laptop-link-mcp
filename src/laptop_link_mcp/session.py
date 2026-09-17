import asyncio
import base64
import copy
import json
import uuid

from .request_store import Journal

READERS = {"server.info", "fs.list", "fs.stat", "fs.read", "fs.hash", "fs.search",
           "exec.poll", "exec.list", "upload.status"}


class RemoteFailure(Exception):
    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(detail["message"])


def display_result(response: dict) -> dict:
    result = copy.deepcopy(response)
    value = result.get("result")
    if not isinstance(value, dict):
        return result
    for stream in (value, value.get("stdout"), value.get("stderr")):
        if isinstance(stream, dict) and isinstance(stream.get("data"), str):
            raw = base64.b64decode(stream["data"], validate=True)
            try:
                stream["text"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                stream["text"] = None  # Base64 is always authoritative, including split UTF-8.
    return result


class Remote:
    def __init__(self, transport, journal: Journal):
        self.transport = transport
        self.journal = journal
        self.boot_id: str | None = None

    async def call(self, method: str, params: dict, *, boot_id: str | None = None) -> dict:
        if method != "server.info" and self.boot_id is None and boot_id is None:
            await self.call("server.info", {})
        request = {"version": 1, "id": str(uuid.uuid4()), "method": method, "params": params}
        if method != "server.info":
            request["bootID"] = boot_id or self.boot_id
        # Validate size before journaling or touching BLE.
        if len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()) > 131_072:
            raise ValueError("Encoded request exceeds 128 KiB")
        mutation = method not in READERS
        if mutation:
            self.journal.save(request)
        return await self._submit(request, mutation)

    async def _submit(self, request: dict, mutation: bool) -> dict:
        try:
            response = await self.transport.exchange(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise RemoteFailure({"code": "outcome_unknown" if mutation else "transport_error",
                                 "message": str(exc), "request_id": request["id"],
                                 "bootID": request.get("bootID"),
                                 "recovery": "Use link_retry with this request_id; do not create a new mutation."
                                 if mutation else "Reconnect with link_status and retry the read."}) from exc
        if mutation:
            self.journal.complete(request["id"], response)
        if request["method"] == "server.info" and not response.get("error"):
            self.boot_id = response["bootID"]
        return self._result(response)

    @staticmethod
    def _result(response: dict) -> dict:
        if response.get("error"):
            raise RemoteFailure({**response["error"], "request_id": response["id"],
                                 "bootID": response["bootID"]})
        return display_result(response)

    async def retry(self, request_id: str) -> dict:
        request, response = self.journal.get(request_id)
        if response is not None:
            return self._result(response)
        # Original boot and complete parameters are immutable, including across process restarts.
        return await self._submit(request, True)

    async def keepalive(self):
        while True:
            await asyncio.sleep(60)
            if self.transport.process is None:
                continue
            try:
                # Do not silently adopt a new boot ID: only explicit link_status does that.
                request = {"version": 1, "id": str(uuid.uuid4()), "method": "server.info", "params": {}}
                await self.transport.exchange(request)
            except Exception:
                pass  # A later user tool call reconnects; no mutation is retried here.
