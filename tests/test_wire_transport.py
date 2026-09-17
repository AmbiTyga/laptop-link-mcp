import copy

import pytest

from laptop_link_mcp.wire_transport import WireTransport


class Factory:
    def __init__(self, formats):
        self.formats = formats
        self.calls = []
        self.instances = []
        self.fail_protobuf = False

    def __call__(self, command, timeout):
        owner = self

        class Bridge:
            def __init__(self):
                self.wire = command[-1]
                self.process = None
                self.closed = False

            async def exchange(self, request):
                owner.calls.append((self.wire, copy.deepcopy(request)))
                self.process = object()
                if self.wire == "protobuf" and owner.fail_protobuf:
                    raise ConnectionError("Injected protobuf failure")
                result = {"wire_formats": owner.formats} if request["method"] == "server.info" else {"job_id": "job"}
                return {"version": 1, "id": request["id"], "bootID": "boot", "result": result}

            async def close(self):
                self.process = None
                self.closed = True

        bridge = Bridge()
        self.instances.append(bridge)
        return bridge


def request(method="server.info"):
    return {"version": 1, "id": "original-id", "method": method, "bootID": "original-boot", "params": {}}


async def test_old_server_keeps_json_without_replaying_status():
    factory = Factory([])
    transport = WireTransport(["bridge"], factory=factory)
    result = await transport.exchange(request())
    assert result["transport"]["wire_format"] == "json"
    assert [wire for wire, _ in factory.calls] == ["json"]


async def test_new_server_upgrades_after_authenticated_probe():
    factory = Factory(["protobuf", "json"])
    transport = WireTransport(["bridge"], factory=factory)
    status = await transport.exchange(request())
    assert status["transport"] == {"wire_format": "protobuf", "selection": "auto"}
    assert [wire for wire, _ in factory.calls] == ["json", "protobuf"]
    assert factory.instances[0].closed
    mutation = request("exec.start")
    await transport.exchange(mutation)
    assert factory.calls[-1] == ("protobuf", mutation)
    assert len(factory.instances) == 2


async def test_pending_retry_probes_read_only_then_preserves_original_identity():
    factory = Factory(["protobuf", "json"])
    transport = WireTransport(["bridge"], factory=factory)
    mutation = request("exec.start")
    await transport.exchange(mutation)
    assert factory.calls[0][1]["method"] == "server.info"
    assert factory.calls[0][1]["id"] != mutation["id"]
    assert "bootID" not in factory.calls[0][1]
    assert factory.calls[1] == ("protobuf", mutation)


async def test_no_silent_downgrade_or_mutation_replay_after_protobuf_failure():
    factory = Factory(["protobuf", "json"])
    factory.fail_protobuf = True
    transport = WireTransport(["bridge"], factory=factory)
    mutation = request("exec.start")
    with pytest.raises(ConnectionError):
        await transport.exchange(mutation)
    assert len([r for _, r in factory.calls if r["method"] == "exec.start"]) == 1
    with pytest.raises(ConnectionError):
        await transport.exchange(request())
    assert [wire for wire, _ in factory.calls] == ["json", "protobuf", "protobuf"]


@pytest.mark.parametrize("mode", ["json", "protobuf"])
async def test_explicit_format_skips_capability_probe(mode):
    factory = Factory(["protobuf", "json"])
    transport = WireTransport(["bridge"], mode=mode, factory=factory)
    mutation = request("exec.start")
    await transport.exchange(mutation)
    assert factory.calls == [(mode, mutation)]
