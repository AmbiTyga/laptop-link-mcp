import asyncio
import base64

import pytest

from laptop_link_mcp.tools import dispatch
from laptop_link_mcp.request_store import Journal
from laptop_link_mcp.session import Remote, RemoteFailure, display_result


async def test_lost_response_retry_survives_mcp_restart(remote, tmp_path):
    remote.transport.drop_reply = True
    with pytest.raises(RemoteFailure) as caught:
        await dispatch(remote, "link_exec_start", {"shell": "echo once"})
    request_id = caught.value.detail["request_id"]
    assert caught.value.detail["code"] == "outcome_unknown"
    assert remote.transport.effects == 1
    original = remote.transport.requests[-1]
    journal = Journal(tmp_path / "state", "test-device")
    try:
        restarted = Remote(remote.transport, journal)
        assert restarted.journal.pending()[0]["request_id"] == request_id
        response = await restarted.retry(request_id)
        assert response["result"]["job_id"] == "job-1"
        assert restarted.transport.requests[-1] == original
        assert restarted.transport.effects == 1
        count = len(restarted.transport.requests)
        assert await restarted.retry(request_id) == response
        assert len(restarted.transport.requests) == count  # Known results do not touch the radio.
        assert journal.pending() == []
    finally:
        journal.close()


async def test_retry_never_changes_boot_after_server_restart(remote):
    remote.transport.drop_reply = True
    with pytest.raises(RemoteFailure) as caught:
        await remote.call("exec.start", {"shell": "echo once"})
    request_id = caught.value.detail["request_id"]
    remote.transport.boot = "boot-b"
    await remote.call("server.info", {})
    with pytest.raises(RemoteFailure) as rejected:
        await remote.retry(request_id)
    assert rejected.value.detail["code"] == "server_changed"
    assert remote.transport.requests[-1]["bootID"] == "boot-a"
    assert remote.transport.effects == 1


async def test_cancelled_call_remains_recoverable(remote):
    async def cancelled(request):
        raise asyncio.CancelledError
    remote.boot_id = "boot-a"
    remote.transport.exchange = cancelled
    with pytest.raises(asyncio.CancelledError):
        await remote.call("fs.write", {"path": "example", "data": ""})
    assert len(remote.journal.pending()) == 1


async def test_device_journals_do_not_cross(remote, tmp_path):
    await remote.call("fs.mkdir", {"path": "one"})
    other = Journal(tmp_path / "state", "different-device")
    try:
        with pytest.raises(ValueError, match="Unknown request"):
            other.get(remote.transport.requests[-1]["id"])
    finally:
        other.close()


@pytest.mark.parametrize("name,arguments", [
    ("link_write_file", {"path": "x", "text": "a", "data": "YQ=="}),
    ("link_write_file", {"path": "x", "text": "é" * 32769}),
    ("link_write_file", {"path": "x", "data": "not-base64!"}),
    ("link_exec_start", {"shell": "ls", "executable": "/bin/ls"}),
    ("link_exec_start", {"shell": "ls", "args": ["ignored"]}),
    ("link_exec_start", {"shell": "ls", "timeout_seconds": 0}),
    ("link_read_file", {"path": "x", "length": 65537}),
    ("link_delete", {"path": "x", "typo": True}),
    ("link_upload_chunk", {"upload_id": "x", "offset": 0, "data": ""}),
])
async def test_invalid_tool_arguments_never_touch_transport(remote, name, arguments):
    with pytest.raises(ValueError):
        await dispatch(remote, name, arguments)
    assert remote.transport.requests == []


async def test_utf8_write_encodes_bytes(remote):
    await dispatch(remote, "link_write_file", {"path": "x", "text": "Hello 🌍"})
    params = remote.transport.requests[-1]["params"]
    assert base64.b64decode(params["data"]) == "Hello 🌍".encode()
    assert "text" not in params


def test_binary_output_preserves_bytes():
    data = base64.b64encode(b"\xff\xe2\x82").decode()
    response = display_result({"result": {"stdout": {"data": data}, "stderr": {"data": "b2s="}}})
    assert response["result"]["stdout"] == {"data": data, "text": None}
    assert response["result"]["stderr"]["text"] == "ok"
