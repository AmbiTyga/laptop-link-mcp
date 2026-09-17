import pytest

from laptop_link_mcp.file_transfer import upload
from laptop_link_mcp.session import RemoteFailure


async def test_interrupted_upload_reports_staged_identity(tmp_path):
    class BadOffsetRemote:
        async def call(self, method, params, **kwargs):
            if method == "server.info":
                return {"bootID": "test-boot"}
            if method == "upload.begin":
                return {"result": {"upload_id": "staged-file"}}
            if method == "upload.chunk":
                return {"result": {"offset": 999}}
            raise AssertionError("Must not commit after invalid progress")

    source = tmp_path / "source"
    source.write_bytes(b"hello")
    with pytest.raises(RemoteFailure) as failure:
        await upload(BadOffsetRemote(), str(source), "destination")
    assert failure.value.detail["upload_id"] == "staged-file"
    assert failure.value.detail["upload_bootID"] == "test-boot"
    assert failure.value.detail["code"] == "upload_interrupted"
    assert failure.value.detail["last_confirmed_offset"] == 0
