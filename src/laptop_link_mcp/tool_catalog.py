"""Explicit tool schemas: unknown parameters are rejected before any remote action."""
from dataclasses import dataclass


def string(description="", **kwargs):
    return {"type": "string", "description": description, **kwargs}


def integer(low=0, high=None):
    return {"type": "integer", "minimum": low, **({"maximum": high} if high is not None else {})}


def obj(properties, required=(), **extra):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False, **extra}


PATH = string("Path on the remote Mac, relative to the server root or absolute within it.", minLength=1)
BOOL = {"type": "boolean"}
HASH = string("SHA-256 of bytes, lowercase hexadecimal.", pattern="^[a-f0-9]{64}$")
DATA = string("Standard padded base64, at most 65536 decoded bytes.", maxLength=87384)
ID = string(minLength=1)
WRITE = {"path": PATH, "data": DATA, "text": string("UTF-8 text; choose text OR data."),
         "expected_sha256": HASH, "overwrite": BOOL}
CONTENT_CHOICE = [{"required": ["data"]}, {"required": ["text"]}]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    method: str | None
    description: str
    schema: dict
    read_only: bool = False


SPECS = [
    ToolSpec("link_status", "server.info", "Connect/authenticate and report the remote root, bootID and limits. "
             "Call before remote work; this explicitly accepts the current server boot.", obj({}), True),
    ToolSpec("link_list_directory", "fs.list", "List a page on the remote Mac; follow next_offset.",
             obj({"path": PATH, "offset": integer(), "limit": integer(1, 500)}), True),
    ToolSpec("link_stat", "fs.stat", "Inspect remote file metadata.", obj({"path": PATH}, ["path"]), True),
    ToolSpec("link_read_file", "fs.read", "Read remote bytes, base64 plus text when valid UTF-8. "
             "Use next_offset until eof; offsets count bytes.",
             obj({"path": PATH, "offset": integer(), "length": integer(1, 65536)}, ["path"]), True),
    ToolSpec("link_hash", "fs.hash", "Compute remote file SHA-256 for verified edits/transfers.",
             obj({"path": PATH}, ["path"]), True),
    ToolSpec("link_search", "fs.search", "Literal remote filename/content search; inspect truncated/skipped.",
             obj({"path": PATH, "query": string(minLength=1), "content": BOOL, "limit": integer(1, 500)},
                 ["query"]), True),
    ToolSpec("link_write_file", "fs.write", "Atomic remote write up to 64 KiB. Existing file needs "
             "expected_sha256 or overwrite=true. Transport failure may mean it succeeded; use link_retry.",
             obj(WRITE, ["path"], oneOf=CONTENT_CHOICE)),
    ToolSpec("link_append_file", "fs.append", "Append up to 64 KiB to an existing remote file. "
             "Never resubmit with a new ID after connection loss; use link_retry.",
             obj({k: v for k, v in WRITE.items() if k != "overwrite"}, ["path"], oneOf=CONTENT_CHOICE)),
    ToolSpec("link_patch_file", "fs.patch", "Apply sequential unique literal replacements to a UTF-8 "
             "file up to 1 MiB, guarded by its expected SHA-256.",
             obj({"path": PATH, "expected_sha256": HASH, "edits": {"type": "array", "minItems": 1,
                  "maxItems": 100, "items": obj({"old": string(minLength=1), "new": string()}, ["old", "new"])}},
                 ["path", "expected_sha256", "edits"])),
    ToolSpec("link_mkdir", "fs.mkdir", "Create a remote directory.",
             obj({"path": PATH, "parents": BOOL}, ["path"])),
    ToolSpec("link_copy", "fs.copy", "Copy a remote regular file; destination must not exist.",
             obj({"source": PATH, "destination": PATH}, ["source", "destination"])),
    ToolSpec("link_move", "fs.move", "Move a remote file/directory; destination must not exist.",
             obj({"source": PATH, "destination": PATH}, ["source", "destination"])),
    ToolSpec("link_delete", "fs.delete", "Delete a remote entry. recursive=true removes directory contents.",
             obj({"path": PATH, "recursive": BOOL}, ["path"])),
    ToolSpec("link_exec_start", "exec.start", "Start a command on the remote Mac and return job_id. "
             "Use executable+args or shell. No stdin/PTY. timeout_seconds is enforced remotely. "
             "Disconnect/MCP cancellation does not stop the job; use link_exec_cancel.",
             obj({"executable": string(pattern="^/"), "args": {"type": "array", "items": string()},
                  "shell": string(minLength=1), "cwd": PATH,
                  "env": {"type": "object", "additionalProperties": string()},
                  "timeout_seconds": integer(1, 3600)},
                 oneOf=[{"required": ["executable"], "not": {"required": ["shell"]}},
                        {"required": ["shell"], "not": {"anyOf": [{"required": ["executable"]},
                                                                       {"required": ["args"]}]}}])),
    ToolSpec("link_exec_poll", "exec.poll", "Read stdout/stderr and state. Keep separate byte offsets. "
             "After exit, drain until both next_offset equal retained_bytes; report discarded_bytes.",
             obj({"job_id": ID, "stdout_offset": integer(), "stderr_offset": integer(),
                  "max_bytes": integer(1, 32768)}, ["job_id"]), True),
    ToolSpec("link_exec_cancel", "exec.cancel", "Request process-group termination on the remote Mac. "
             "Poll to confirm completion and retrieve remaining output.", obj({"job_id": ID}, ["job_id"])),
    ToolSpec("link_exec_list", "exec.list", "List jobs for this server boot; use poll for full output.",
             obj({}), True),
    ToolSpec("link_upload_begin", "upload.begin", "Start a resumable verified upload (default server cap 64 MiB).",
             obj({"path": PATH, "size": integer(), "sha256": HASH, "expected_sha256": HASH,
                  "overwrite": BOOL}, ["path", "size", "sha256"])),
    ToolSpec("link_upload_chunk", "upload.chunk", "Send <=64 KiB at the exact upload offset. "
             "Use link_retry on ambiguous failure before advancing the offset.",
             obj({"upload_id": ID, "offset": integer(), "data": DATA}, ["upload_id", "offset", "data"])),
    ToolSpec("link_upload_status", "upload.status", "Inspect upload progress for this server boot.",
             obj({"upload_id": ID}, ["upload_id"]), True),
    ToolSpec("link_upload_commit", "upload.commit", "Verify hash and atomically install a completed upload.",
             obj({"upload_id": ID}, ["upload_id"])),
    ToolSpec("link_upload_abort", "upload.abort", "Discard an incomplete upload.",
             obj({"upload_id": ID}, ["upload_id"])),
    ToolSpec("link_terminal_open", "terminal.open", "Open a persistent interactive zsh PTY and a visible window on the remote Mac. "
             "No automatic command timeout; state survives BLE disconnect. Output is combined, with ANSI control sequences.",
             obj({"cwd": PATH, "cols": integer(2, 500), "rows": integer(2, 200),
                  "env": {"type": "object", "additionalProperties": string()}})),
    ToolSpec("link_terminal_list", "terminal.list", "List terminal sessions, ownership, and control epochs for this server boot.",
             obj({}), True),
    ToolSpec("link_terminal_read", "terminal.read", "Read combined terminal bytes and current ownership. Follow output.next_offset; "
             "output.truncated means older bytes expired. Shell prompts do not prove command success.",
             obj({"session_id": ID, "offset": integer(), "max_bytes": integer(1, 32768)}, ["session_id"]), True),
    ToolSpec("link_terminal_write", "terminal.write", "Send exact text or base64 bytes to a persistent terminal. "
             "Include newline to submit a command; send byte 0x03 for Ctrl+C. Requires current agent ownership and control_epoch. "
             "accepted_bytes means queued input, not command completion. Use link_retry after ambiguous failure; never resend under a new ID.",
             obj({"session_id": ID, "control_epoch": integer(1), "text": string(), "data": DATA},
                 ["session_id", "control_epoch"], oneOf=CONTENT_CHOICE)),
    ToolSpec("link_terminal_resize", "terminal.resize", "Resize the PTY and visible terminal; requires current agent ownership/epoch.",
             obj({"session_id": ID, "control_epoch": integer(1), "cols": integer(2, 500), "rows": integer(2, 200)},
                 ["session_id", "control_epoch", "cols", "rows"])),
    ToolSpec("link_terminal_close", "terminal.close", "End a terminal session and its job-control groups. "
             "Requires current agent ownership/epoch. The local user can always end it from the window.",
             obj({"session_id": ID, "control_epoch": integer(1)}, ["session_id", "control_epoch"])),
    ToolSpec("link_retry", None, "Recover a journaled mutation using its ORIGINAL ID, boot and parameters. "
             "Completed responses come from the journal; pending requests are resubmitted with server deduplication. "
             "A server_changed error requires inspecting the outcome, never a blind fresh mutation.",
             obj({"request_id": ID}, ["request_id"])),
    ToolSpec("link_pending_requests", None, "List up to 100 unfinished local mutation identities, newest first, "
             "including calls cancelled by the MCP host. Does not expose command/file payloads.", obj({}), True),
    ToolSpec("link_upload", None, "Transfer an absolute LOCAL file path to the remote Mac in verified chunks. "
             "May take minutes. On failure, use returned upload_id/request_id with recovery tools.",
             obj({"local_path": string(pattern="^/"), "remote_path": PATH,
                  "expected_sha256": HASH, "overwrite": BOOL}, ["local_path", "remote_path"])),
    ToolSpec("link_download", None, "Download a remote file to an absolute LOCAL path (default max 64 MiB). "
             "Verify SHA-256 and replace atomically. Local parent must exist; overwrite defaults false.",
             obj({"remote_path": PATH, "local_path": string(pattern="^/"), "overwrite": BOOL,
                  "max_bytes": integer(0, 1073741824)}, ["remote_path", "local_path"])),
]

CATALOG = {spec.name: spec for spec in SPECS}
