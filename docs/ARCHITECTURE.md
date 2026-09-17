# Architecture

`src/laptop_link_mcp` owns MCP schemas, validation, durable mutation identities, text/base64 presentation, and streamed local file transfers. It uses the official `mcp` Python SDK's stdio transport; dependencies are pinned in `uv.lock`. The Python layer does not implement BLE authentication or encryption.

`native/LinkBridge` owns a persistent CoreBluetooth central connection. It takes one newline-delimited RPC request at a time on stdin and returns a JSON response on stdout. It keeps handshake keys and sequence counters alive across calls. Errors go to stderr and terminate the subprocess. The Python transport closes a subprocess after malformed replies, disconnects, timeouts, or cancellation, so late replies cannot be mistaken for a subsequent request. It never interprets an ATT write acknowledgement as completed execution.

`native/LinkProtocol` and `native/LinkBridge/LinkServiceIDs.swift` were copied from the companion Laptop Link project on 2026-09-17. `LinkSession.swift` adapts its one-shot central client to a persistent single-request-at-a-time session. The shared files are intentionally checked in so each repository can build independently without fetching Swift packages. When changing the wire protocol, review both projects and update these copies together. The existing Laptop Link server requires no changes for this MCP adapter.

The [Laptop Link protocol reference](https://github.com/AmbiTyga/laptop-link/blob/main/docs/PROTOCOL.md) defines framing, authentication, limits, and operations. Version 1 uses a 32-byte enrollment key, mutual HMAC proof, directional HKDF-derived keys, and AES-GCM counters. Application frames are fragmented to CoreBluetooth's negotiated write length. Server notification flow control remains in Laptop Link.

## Execution boundaries

- MCP stdio stays local to the controlling Mac. BLE is the only transport to the remote Mac.
- The journal commits a complete mutation request before the transport receives it. Transport failures leave that identity pending. The journal is scoped to the selected key and optional advertised-name filter.
- Read requests are not journaled. Mutations retain both successful and failed server responses. Explicit retry returns known responses locally or sends the exact pending request to the server.
- Boot IDs are not substituted during retries. A status call explicitly selects the current boot for new operations. Keepalives cannot silently change that selection.
- Cancelling an MCP call tears down its BLE exchange, but cannot undo remotely accepted work. Remote cancellation is a separate explicit command-job operation.
- File transfers pin a server boot for all constituent requests. Uploads use the server's chunked staging and atomic commit. Downloads stage beside the local destination and verify hashes before atomic publication.

## Limits

The native bridge is macOS-only. The skill and MCP interface are agent-independent; this does not make the Bluetooth runtime cross-platform. One connection handles one RPC at a time. Large transfers occupy the radio and may exceed host tool-call deadlines. The server's default 8192 mutation admission limit includes upload chunks and is per server run.

The journal grows until managed by its owner. Keep it while pending outcomes need recovery. Keys, journal contents, and generated artifacts must never be committed. Native app bundles are ad-hoc signed for local use, not notarized distributions.
