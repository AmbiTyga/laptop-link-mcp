import base64
import hashlib
import os
import tempfile
from pathlib import Path

from .session import RemoteFailure


async def upload(remote, local_path, remote_path, overwrite=False, expected_sha256=None):
    info = await remote.call("server.info", {})
    boot = info["bootID"]
    path = Path(local_path)
    if not path.is_file():
        raise ValueError("Upload source must be a local regular file")
    with path.open("rb") as source:
        size = os.fstat(source.fileno()).st_size
        if size > 64 * 1024 * 1024:
            raise ValueError("Convenience upload limit is 64 MiB; use chunk tools for custom server limits")
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        params = {"path": remote_path, "size": size, "sha256": digest, "overwrite": overwrite}
        if expected_sha256:
            params["expected_sha256"] = expected_sha256
        begin = await remote.call("upload.begin", params, boot_id=boot)
        upload_id = begin["result"]["upload_id"]
        offset = 0
        try:
            while chunk := source.read(65536):
                reply = await remote.call("upload.chunk", {"upload_id": upload_id, "offset": offset,
                                          "data": base64.b64encode(chunk).decode()}, boot_id=boot)
                next_offset = offset + len(chunk)
                if reply["result"]["offset"] != next_offset:
                    raise ValueError("Invalid upload offset response")
                offset = next_offset
            result = await remote.call("upload.commit", {"upload_id": upload_id}, boot_id=boot)
            result["upload_id"] = upload_id
            return result
        except RemoteFailure as exc:
            exc.detail.update(upload_id=upload_id, last_confirmed_offset=offset, upload_bootID=boot)
            raise
        except (OSError, ValueError) as exc:
            raise RemoteFailure({"code": "upload_interrupted", "message": str(exc),
                                 "upload_id": upload_id, "last_confirmed_offset": offset,
                                 "upload_bootID": boot,
                                 "recovery": "Inspect link_upload_status, then resume the same source or abort."}) from exc


async def download(remote, remote_path, local_path, overwrite=False, max_bytes=64 * 1024 * 1024):
    target = Path(local_path)
    if not target.is_absolute():
        raise ValueError("Download destination must be absolute")
    if os.path.lexists(target) and not overwrite:
        raise ValueError("Local destination exists; set overwrite=true deliberately")
    info = await remote.call("server.info", {})
    boot = info["bootID"]
    initial = await remote.call("fs.hash", {"path": remote_path}, boot_id=boot)
    digest = hashlib.sha256()
    offset = 0
    fd, name = tempfile.mkstemp(prefix=".ble-download-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as sink:
            while True:
                response = await remote.call("fs.read", {"path": remote_path, "offset": offset,
                                                       "length": 65536}, boot_id=boot)
                result = response["result"]
                raw = base64.b64decode(result["data"], validate=True)
                if result["size"] > max_bytes or offset + len(raw) > max_bytes:
                    raise ValueError("Remote file exceeds download max_bytes")
                if result["next_offset"] != offset + len(raw) or (not raw and not result["eof"]):
                    raise ValueError("Invalid download progress")
                sink.write(raw)
                digest.update(raw)
                offset += len(raw)
                if result["eof"]:
                    break
            sink.flush()
            os.fsync(sink.fileno())
        final = await remote.call("fs.hash", {"path": remote_path}, boot_id=boot)
        if digest.hexdigest() != initial["result"]["sha256"] or digest.hexdigest() != final["result"]["sha256"]:
            raise ValueError("Source changed or checksum mismatch; local destination was not replaced")
        if overwrite:
            os.replace(name, target)
        else:
            os.link(name, target)  # Exclusive atomic publication, even if a competing writer creates target.
        return {"local_path": str(target), "remote_path": remote_path, "size": offset,
                "sha256": digest.hexdigest(), "bootID": boot}
    finally:
        if os.path.exists(name):
            os.unlink(name)
