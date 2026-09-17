# Recover BLE work

## Lost response

A tool error with `code: outcome_unknown` includes `request_id` and the original `bootID`. `link_retry(request_id)` retrieves a saved response or submits the exact stored request. The remote server deduplicates identical mutations within one server run. Do not synthesize a new ID or edit parameters to retry.

If the host cancelled the tool before returning an error, `link_pending_requests` lists the newest 100 pending identities with method and boot. Retry the relevant identity to recover a lost command job ID or file-operation result. The journal is private to the selected enrollment key and name filter; changing them does not migrate history.

After one explicit recovery attempt fails with another transport error, check connection status and report the pending ID and uncertainty. Avoid an unbounded retry loop. The user may restore Bluetooth/range or resume later with the same journal.

## Remote restart

`server_changed` means the old mutation belongs to a different server boot. A fresh `link_status` accepts the new boot for new operations, but cannot make old retries safe. Inspect files, hashes, and relevant side effects before deciding whether the user's intended action remains necessary. Previous jobs/uploads/terminal sessions and server deduplication do not survive a restart. Never silently resubmit a command merely because its old job ID is missing.

## Uploads

`link_upload` returns `upload_id` and `last_confirmed_offset` when a failure happens after staging begins. Its `request_id` identifies the individual pending mutation, not the whole transfer.

1. Recover that mutation using `link_retry` first. A lost `upload.begin` response yields the upload ID; a lost `upload.commit` response may show the transfer is already complete.
2. For an existing staged upload, use `link_upload_status` to obtain its offset. Resume from that exact byte offset with `link_upload_chunk` (nonempty base64 chunks <=65536 bytes), then `link_upload_commit`.
3. Resume only with the same source bytes/hash. If continuation is unnecessary, use `link_upload_abort` on the known upload ID.

Do not restart the entire convenience upload after an ambiguous commit without inspecting the destination. Remote uploads expire after an hour of inactivity and are lost on server restart. If a local read fails or the source changes, the error includes the staged upload ID so it can be inspected or aborted. If the MCP host cancelled the entire call, pending requests can identify an in-flight mutation; the server also expires abandoned uploads.

## Downloads and commands

Failed downloads leave the previous destination intact and remove the temporary file. Fix the reported condition and start a new download; it does not mutate remote state. An existing local destination requires explicit `overwrite: true`.

Transport timeouts apply to BLE exchanges. Command execution timeouts run on the remote Mac even while disconnected. Query a known job with `link_exec_poll`, use `link_exec_cancel` when stopping it is intended, and retrieve remaining stdout/stderr. A cancel request means termination was requested, not that all effects were rolled back.

## Interactive terminal reconnects

Use `link_terminal_list` and `link_terminal_read` to find the intended session after reconnecting to the same boot. Keep its absolute output cursor; report `output.truncated` if bytes expired. Recover an ambiguous terminal write through its original `link_retry` identity before sending further input. A successful cached retry does not grant control: inspect the current owner and epoch. If the user has taken control, wait for Return Control without opening another session or using a background command to bypass the handoff. See [terminal sessions](terminal.md).
