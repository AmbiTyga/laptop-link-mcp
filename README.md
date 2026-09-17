# Laptop Link MCP

Connect AI coding tools to another laptop over Bluetooth Low Energy. Laptop Link MCP exposes file operations, file transfers, and CLI commands through the Model Context Protocol (MCP), using [Laptop Link](https://github.com/AmbiTyga/laptop-link) on the remote laptop.

The current implementation supports **two Macs**. A persistent Swift CoreBluetooth bridge carries authenticated, encrypted **Protobuf** requests; the official Python MCP SDK exposes them to Claude Code, Codex, and other clients that can launch a local stdio MCP server. No IP network connection is needed between the laptops. Older servers remain accessible through JSON compatibility mode.

```text
Claude / Codex / MCP client
          │ stdio MCP
       laptop-link-mcp (Python)
          │ private JSON-lines pipe
       BLE bridge (Swift)
          │ encrypted binary Protobuf over BLE
       Laptop Link (remote Mac)
          │
       files + command jobs
```

## Setup

On the remote Mac, build and launch [Laptop Link](https://github.com/AmbiTyga/laptop-link), select its workspace, and privately transfer its enrollment key to the controlling Mac.

On the controlling Mac, install Python 3.11+, [uv](https://docs.astral.sh/uv/), and a Swift 6 compiler with a compatible macOS SDK. Swift 6.3.3 is the tested toolchain. macOS 13+ is the build target; see [validation](docs/VALIDATION.md) for tested systems.

```sh
git clone https://github.com/AmbiTyga/laptop-link-mcp.git
cd laptop-link-mcp
./scripts/setup.sh
chmod 600 /private/path/client.key
```

`setup.sh` installs locked Python dependencies and builds `dist/LaptopLinkBridge.app`. Set `LINK_SWIFTC` or `LINK_SDK` to select a compiler or SDK explicitly. The Swift build uses `swiftc` directly, without Swift Package Manager or downloaded Swift packages. Python packages are downloaded during setup; subsequent launches need no network access.

Both laptops must be awake, within BLE range, and have Bluetooth enabled. Allow Bluetooth access for the bridge or the application launching it when macOS prompts. Keep the bridge inside its app bundle so macOS can read its Bluetooth usage description.

## Connect your agent

Use absolute paths. The MCP server starts lazily: connecting the agent does not contact the remote laptop until a tool is called.

**Claude Code**

```sh
claude mcp add --transport stdio --scope user laptop-link -- \
  /absolute/path/laptop-link-mcp/scripts/run.sh --key /private/path/client.key
```

**Codex**

```sh
codex mcp add laptop-link -- \
  /absolute/path/laptop-link-mcp/scripts/run.sh --key /private/path/client.key
```

**Other local MCP clients**, including Claude Desktop, can use this stdio entry in their MCP configuration:

```json
{
  "mcpServers": {
    "laptop-link": {
      "command": "/absolute/path/laptop-link-mcp/scripts/run.sh",
      "args": ["--key", "/private/path/client.key", "--timeout", "120"]
    }
  }
}
```

Configuration containers differ by client; use its documented location. Set the host's tool timeout above the BLE request timeout. Complete file transfers may need several minutes. `--timeout` controls each BLE RPC; `timeout_seconds` on `link_exec_start` controls command execution on the remote laptop.

See [client installation](docs/INSTALLATION.md) for the portable skill, configuration details, and troubleshooting. Official references: [Claude MCP](https://code.claude.com/docs/en/mcp), [Codex MCP](https://developers.openai.com/codex/mcp).

## Install the portable skill

The repository includes [`skills/laptop-link/SKILL.md`](skills/laptop-link/SKILL.md), using the open [Agent Skills format](https://agentskills.io/specification). It teaches the agent remote paths, output polling, verified edits, transfers, and recovery after a disconnect.

```sh
# Claude Code
python3 scripts/install-skill.py --target claude

# Codex / shared Agent Skills directory
python3 scripts/install-skill.py --target codex

# Any other framework's documented skill directory
python3 scripts/install-skill.py --directory /path/to/framework/skills
```

The installer copies only the skill and its references, never keys or machine configuration. It refuses to overwrite an existing installation. The skill is portable across Agent Skills-compatible hosts; frameworks without skill support can load its Markdown as instructions. Installing a skill does not install or register the MCP server. Cloud-only agents cannot directly access a local Mac's Bluetooth adapter.

## Tools

| Area | Tools |
| --- | --- |
| Interactive terminal | `link_terminal_open`, `link_terminal_list`, `link_terminal_read`, `link_terminal_write`, `link_terminal_resize`, `link_terminal_close` |
| Connection | `link_status` |
| Read and inspect | `link_list_directory`, `link_stat`, `link_read_file`, `link_hash`, `link_search` |
| Edit and manage | `link_write_file`, `link_append_file`, `link_patch_file`, `link_mkdir`, `link_copy`, `link_move`, `link_delete` |
| Command jobs | `link_exec_start`, `link_exec_poll`, `link_exec_cancel`, `link_exec_list` |
| File transfers | `link_upload`, `link_download` |
| Resumable upload primitives | `link_upload_begin`, `link_upload_chunk`, `link_upload_status`, `link_upload_commit`, `link_upload_abort` |
| Recovery | `link_retry`, `link_pending_requests` |

Start with `link_status` to check the remote workspace and limits. File paths refer to that Mac; only `local_path` in upload/download refers to the controlling laptop. Text writes accept `text`; binary writes accept `data` as base64. Reads and command streams always preserve base64 bytes, adding `text` when the chunk is valid UTF-8.

Commands return a job ID immediately. Poll for stdout, stderr, exit status, and timeout/cancellation state. Carry separate byte offsets for stdout and stderr and drain both streams after exit. Commands are noninteractive: no stdin, PTY, or password prompts.

## Connection and recovery

The default `--wire auto` first queries server capabilities over authenticated legacy JSON, then reconnects with Protobuf when supported. Status responses include `transport.wire_format` (`protobuf` or `json`). Use `--wire protobuf` to require the new format, or `--wire json` for explicit legacy operation. Once Protobuf is selected, a failure never triggers a silent downgrade or mutation replay.

Protobuf carries raw file/output bytes and ciphertext, removing both layers of base64 on BLE. A 65536-byte upload chunk measured 65747 encrypted/framed bytes, versus 116861 with JSON (43.7% less). Local MCP and bridge pipes remain JSON/base64. SwiftProtobuf 1.38.1 and generated sources are vendored for offline native builds; `Protocol/ble_wire.proto` defines the wire format.

One native subprocess keeps its authenticated BLE session across requests, serializes RPCs, and sends a keepalive every 60 seconds. A transport failure closes that session. The next call can reconnect; **mutations are never automatically replayed**.

Before each mutation, the MCP server durably records its UUID, server boot ID, and complete parameters in a private SQLite journal. A lost response includes `request_id`; use `link_retry` to replay the exact request. The remote server deduplicates within the same boot. Known results are returned from the journal without another BLE request. `link_pending_requests` finds interrupted calls, including MCP cancellations.

After a remote restart, old requests retain their original boot ID and are rejected. Inspect the actual outcome before deliberately creating a new operation. A disconnected or cancelled MCP call does **not** cancel a remote command. Use `link_exec_cancel` or its execution timeout.

The journal defaults to `~/Library/Application Support/LaptopLinkMCP/requests.sqlite3`. Its directory must be mode 700 and the file mode 600. It contains command arguments, file data, and responses, but no enrollment key. It is not encrypted at rest. Protect it as workspace data; deleting it loses retry identities. `--state-dir` selects a dedicated location.

The enrollment key authorizes the remote account's operations. Filesystem tools respect the configured remote root; commands run with the server user's permissions and are not an OS sandbox. Keep keys out of source control. Name filtering (`--name`) is a discovery convenience; the key authenticates the peer.

## Development

```sh
./scripts/setup.sh
./scripts/check.sh
```

Optional integration tests against a separately built Laptop Link server:

```sh
LINK_TEST_SERVER=/absolute/path/laptop-link/dist/LaptopLinkServer.app/Contents/MacOS/link-server \
  ./scripts/check.sh
```

The tests use temporary workspaces. Hardware checks are opt-in; see [validation](docs/VALIDATION.md). Native protocol sources are included in this repository, so a sibling `laptop-link` checkout is not required to build or run. See [architecture](docs/ARCHITECTURE.md) for source provenance and the transport boundary.

## Shared interactive terminal

Use the six `link_terminal_*` tools for a visible persistent shell with local Take Control / Return Control. Update the receiving server app too. See [terminal sessions](skills/laptop-link/references/terminal.md) for input, ownership, and retry semantics.
