import copy

import pytest

from laptop_link_mcp.request_store import Journal
from laptop_link_mcp.session import Remote


class MemoryTransport:
    """Deterministic model of server boot/deduplication, with injectable lost replies."""
    def __init__(self):
        self.boot = "boot-a"
        self.requests = []
        self.cache = {}
        self.effects = 0
        self.drop_reply = False

    async def exchange(self, request):
        self.requests.append(copy.deepcopy(request))
        response = {"version": 1, "id": request["id"], "bootID": self.boot}
        if request["method"] == "server.info":
            return {**response, "result": {"root": "/remote/workspace"}}
        if request["bootID"] != self.boot:
            return {**response, "error": {"code": "server_changed", "message": "Server restarted"}}
        if request["id"] not in self.cache:
            self.effects += 1
            self.cache[request["id"]] = {**response, "result": {"job_id": f"job-{self.effects}"}}
        if self.drop_reply:
            self.drop_reply = False
            raise ConnectionError("Injected lost response AFTER execution")
        return self.cache[request["id"]]


@pytest.fixture
def remote(tmp_path):
    journal = Journal(tmp_path / "state", "test-device")
    remote = Remote(MemoryTransport(), journal)
    yield remote
    journal.close()
