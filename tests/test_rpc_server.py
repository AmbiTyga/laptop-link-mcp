"""Optional integration tests against the actual companion server, using pipes."""
import asyncio
import base64
import hashlib
import os

import pytest

from laptop_link_mcp.tools import dispatch
from laptop_link_mcp.request_store import Journal
from laptop_link_mcp.session import Remote, RemoteFailure
from laptop_link_mcp.bridge import BridgeTransport

SERVER = os.environ.get("LINK_TEST_SERVER")
pytestmark = pytest.mark.skipif(not SERVER, reason="Set LINK_TEST_SERVER to a built Laptop Link server")


@pytest.fixture
async def native(tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    config = tmp_path / "configuration/server.json"
    process = await asyncio.create_subprocess_exec(SERVER, "--init", "--root", str(root), "--config", str(config),
                                                   stdout=asyncio.subprocess.DEVNULL)
    assert await process.wait() == 0
    transport = BridgeTransport([SERVER, "--stdio", "--config", str(config)], timeout=5)
    journal = Journal(tmp_path / "journal", "native-test")
    remote = Remote(transport, journal)
    try:
        yield remote, root
    finally:
        await transport.close()
        journal.close()


async def test_binary_transfers_and_guarded_edits(native, tmp_path):
    remote, root = native
    source = tmp_path / "source.bin"
    source.write_bytes(bytes(range(256)) * 300)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    uploaded = await dispatch(remote, "link_upload", {"local_path": str(source), "remote_path": "payload.bin"})
    assert uploaded["result"]["sha256"] == digest
    assert (root / "payload.bin").read_bytes() == source.read_bytes()
    destination = tmp_path / "download.bin"
    await dispatch(remote, "link_download", {"remote_path": "payload.bin", "local_path": str(destination)})
    assert destination.read_bytes() == source.read_bytes()
    with pytest.raises(ValueError, match="exists"):
        await dispatch(remote, "link_download", {"remote_path": "payload.bin", "local_path": str(destination)})
    destination.write_bytes(b"keep this")
    with pytest.raises(ValueError, match="max_bytes"):
        await dispatch(remote, "link_download", {"remote_path": "payload.bin", "local_path": str(destination),
                                               "overwrite": True, "max_bytes": 1})
    assert destination.read_bytes() == b"keep this"
    assert list(tmp_path.glob(".ble-download-*")) == []
    write = await dispatch(remote, "link_write_file", {"path": "text", "text": "hello world"})
    await dispatch(remote, "link_patch_file", {"path": "text", "expected_sha256": write["result"]["sha256"],
                                              "edits": [{"old": "world", "new": "BLE"}]})
    assert (root / "text").read_text() == "hello BLE"
    with pytest.raises(RemoteFailure) as rejected:
        await dispatch(remote, "link_write_file", {"path": "text", "text": "stale",
                                                  "expected_sha256": write["result"]["sha256"]})
    assert rejected.value.detail["code"] == "conflict"


async def wait_for_job(remote, job):
    async with asyncio.timeout(8):
        while True:
            reply = await dispatch(remote, "link_exec_poll", {"job_id": job})
            if reply["result"]["state"] != "running":
                return reply["result"]
            await asyncio.sleep(0.05)


async def test_command_stdout_stderr_exit_and_exact_retry(native):
    remote, _ = native
    start = await dispatch(remote, "link_exec_start", {"shell": "printf hello; printf warning >&2; exit 7"})
    repeated = await dispatch(remote, "link_retry", {"request_id": start["id"]})
    assert repeated == start
    result = await wait_for_job(remote, start["result"]["job_id"])
    assert result["exit_code"] == 7
    assert result["stdout"]["text"] == "hello"
    assert base64.b64decode(result["stderr"]["data"]) == b"warning"


async def test_command_timeout_and_cancellation(native):
    remote, _ = native
    start = await dispatch(remote, "link_exec_start", {"shell": "printf ready; /bin/sleep 30", "timeout_seconds": 1})
    timed_out = await wait_for_job(remote, start["result"]["job_id"])
    assert timed_out["state"] == "timed_out"
    assert timed_out["stdout"]["text"] == "ready"
    start = await dispatch(remote, "link_exec_start", {"executable": "/bin/sleep", "args": ["30"]})
    await dispatch(remote, "link_exec_cancel", {"job_id": start["result"]["job_id"]})
    assert (await wait_for_job(remote, start["result"]["job_id"]))["state"] == "cancelled"


async def test_empty_file_transfer(native, tmp_path):
    remote, root = native
    source = tmp_path / "empty"
    source.write_bytes(b"")
    await dispatch(remote, "link_upload", {"local_path": str(source), "remote_path": "empty"})
    assert (root / "empty").read_bytes() == b""
    await dispatch(remote, "link_download", {"remote_path": "empty", "local_path": str(tmp_path / "received")})
    assert (tmp_path / "received").read_bytes() == b""
