# Client and skill installation

Install Laptop Link MCP on the Mac running your agent. Install Laptop Link on the other Mac. The MCP endpoint uses local stdin/stdout, not an HTTP listener. Keep the enrollment key as a private local file; pass its path, never its contents.

## Skill locations

| Client | Personal skill directory | Project skill directory |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/laptop-link` | `<project>/.claude/skills/laptop-link` |
| Codex / Agent Skills | `~/.agents/skills/laptop-link` | `<project>/.agents/skills/laptop-link` |
| Other compatible frameworks | Their documented skill discovery directory | Their documented project directory |

Run `scripts/install-skill.py --target claude` or `--target codex` from this repository. For a project installation, pass `--directory /absolute/project/.claude/skills` or `.agents/skills`. A custom `--directory` supports any framework that discovers standard skill folders. The script adds the `laptop-link` subdirectory itself.

Restart or reload the host's skill discovery as required. Ask it to use `laptop-link` for work on the BLE-connected laptop. Claude Code can invoke it as `/laptop-link`; Codex can invoke it as `$laptop-link`. Tool names may have a host-specific MCP prefix; the skill refers to their stable `link_*` suffixes.

For hosts without a skill loader, include `SKILL.md` and its referenced recovery guide in the agent's instructions. The file format is portable, but skill installation paths and MCP configuration are framework-specific. The skill alone cannot provide Bluetooth access or install a missing runtime. A hosted Claude chat does not gain local Bluetooth simply by receiving the skill file.

References: [Agent Skills specification](https://agentskills.io/specification), [Claude skills](https://code.claude.com/docs/en/skills), [Codex skills](https://developers.openai.com/codex/skills).

## MCP launch options

`scripts/run.sh` resolves its own repository location and uses the prepared `.venv`. It does not download packages at startup and works regardless of the agent's working directory.

| Option | Meaning |
| --- | --- |
| `--key PATH` | Required private 32-byte enrollment key file |
| `--name NAME` | Optional exact advertised-name filter |
| `--wire auto\|protobuf\|json` | Default auto: authenticated capability selection; protobuf requires a v2-capable server |
| `--timeout SECONDS` | Per-RPC BLE timeout, 1–3600; default 120 |
| `--state-dir PATH` | Private directory for durable mutation records |

Calling `.venv/bin/laptop-link-mcp` directly also requires `--bridge /absolute/path/to/link-bridge`. Use the executable under `dist/LaptopLinkBridge.app/Contents/MacOS/`.

Use a separate state directory when independent histories are desirable. Journal entries are additionally scoped by an enrollment-key fingerprint and name filter. Rotating the key or changing the filter selects a different history. Do not reuse one key across multiple remote machines: a name is not an authenticated device identifier.

For Codex, long file transfers can need a higher `tool_timeout_sec` under the relevant `[mcp_servers.laptop-link]` entry. For other clients, use their equivalent tool timeout. A host timeout can interrupt a transfer while leaving a remotely accepted operation running; recover with the journal tools.

## Troubleshooting

- **Missing executable or Python package:** run `./scripts/setup.sh` again. Keep the whole repository and `.venv` in place; rebuild after moving it because virtualenv launchers contain absolute paths.
- **Compiler/SDK mismatch:** set `LINK_SWIFTC=/path/to/swiftc` and `LINK_SDK=/path/to/compatible/MacOSX.sdk`, then rebuild. The native build bypasses SwiftPM.
- **Bluetooth unavailable:** enable Bluetooth and check macOS Privacy & Security → Bluetooth for the launching application. The remote server must be advertising, both Macs awake, and the key must match.
- **`server_changed`:** the remote server restarted. Inspect outcome, then call `link_status` to accept the new boot for new work. Old retries stay bound to their original boot.
- **Transport timeout:** a submitted command or write may have executed. Use the returned request ID with `link_retry`; if the host cancelled without a result, use `link_pending_requests`.
- **Status reports JSON:** the selected server did not advertise Protobuf support. Build and run the updated Laptop Link server, then restart the MCP process to re-negotiate. `--wire protobuf` never silently falls back to JSON. The local MCP interface continues using JSON in either mode.
- **Permission error for state or key:** the key must be a regular file owned by your account, mode 600; the state directory must be owned by you, mode 700. The journal may contain sensitive file contents.
- **Large command output:** poll both byte streams until fully drained, and report `discarded_bytes` or stream errors. `text: null` means the chunk is binary or splits a UTF-8 character; decode consecutive base64 chunks incrementally.

Only build and use the software on machines you control or are authorized to operate. Command execution is visible in the tool definitions and runs as the remote server's user.

Set `LINK_TRACE=1` in the MCP process environment to log native BLE connection stages to stderr while diagnosing discovery or authentication failures. Standard output remains reserved for protocol messages.
