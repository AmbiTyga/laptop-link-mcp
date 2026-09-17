# Shared terminal sessions

1. Call `link_status`, then open a session or find an existing one with `link_terminal_list`. Session IDs belong to the current server boot.
2. Read with `link_terminal_read`, carrying the absolute `output.next_offset`. Keep raw base64 bytes: text can contain ANSI escape sequences or split UTF-8. If `output.truncated` is true, earlier output expired from bounded history; report that gap.
3. To send input, use `link_terminal_write` with the current `session_id` and `control_epoch`, and either `text` or base64 `data`. Input is exact: append an actual newline to submit a shell command. In JSON, encode it as `\n`; encode Ctrl+C as `\u0003` (byte 0x03). Do not send the literal backslash characters. Read output between commands; an accepted write is not an exit status or proof of completion. The shell's final exit code is only reported when the session ends.
4. On `local_control`, stop sending input, resizing, or closing. Only the user can Return Control in the window. Do not work around the handoff by opening a second terminal or using background commands to continue the same paused work. Reads remain available. On `stale_control`, read the latest output and re-establish shell state before intentionally issuing new input with the new epoch.
5. On transport failure, retain the original request ID and use `link_retry`; never generate a new write to repeat ambiguous keystrokes. The server deduplicates writes. A handoff discards queued bytes not yet written to the PTY, but cannot undo bytes already delivered or commands already running. A cached successful write retry does not grant current control.
6. Closing the window hides it; Show Terminals restores it. BLE disconnect leaves the shell running. `link_terminal_close` (agent-owned session) or End Session (local UI) kills the shell and its job-control groups. Detached processes that deliberately create another OS session are outside that lifecycle. Quitting/restarting the server ends sessions; there is no crash recovery.

PTY stdout/stderr are combined. There is no per-command execution timeout, and interactive shell startup files run under the remote user account. Use existing `link_exec_start` when separate streams, exact per-command exit status, or enforced timeout is required. The workspace controls initial cwd, not a shell sandbox. Local Take Control and Return Control change the epoch; do not assume cwd or variables stayed unchanged while the user owned the terminal.

## Send/read example

Call `link_terminal_open` with `{"cwd":"."}`. Save the returned `result.session_id` and `result.control_epoch`. Use those current values in `link_terminal_write`; this example assumes the returned epoch is 1:

```json
{"session_id":"<returned session_id>","control_epoch":1,"text":"pwd\n"}
```

Then call `link_terminal_read` with that session ID and `offset: 0`. Save `result.output.next_offset` and supply it as `offset` on the next read. Use `result.owner` and `result.control_epoch` to check current control. ANSI control sequences and partial UTF-8 may occur; `output.data` preserves the original bytes.

For Ctrl+C, send `"text":"\u0003"` with the current session ID and epoch. This interrupts the foreground job; it normally leaves the shell available. To answer an interactive prompt, send only the intended answer and newline after reading the prompt. Do not assume the foreground program is always the shell.

Before assuming completion, inspect the actual output or obtain a deliberate shell status marker. A returned shell prompt alone does not establish success. When exact per-command exit codes and deadlines are central to the task, choose the background command tools instead.
