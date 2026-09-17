# Validation — 2026-09-17

The MCP adapter was tested on an Apple Silicon Mac with Python 3.12.7, Swift 6.3.3, and the macOS 26.4 SDK. The native bridge targets macOS 13+. The remote Mac used the compatible protocol-v1 server and reported macOS 26.7, arm64, 24 GiB memory, and 10 CPU cores.

## Automated checks

`LINK_TEST_SERVER=/path/to/link-server ./scripts/check.sh` runs 32 checks, including six against the actual companion server through its local stdio diagnostic endpoint. Without `LINK_TEST_SERVER`, those six are explicitly skipped. The remaining checks do not need Bluetooth hardware or credentials.

Coverage:

- Official MCP initialization, tool discovery, structured results, error results, and request retry over a real stdio subprocess.
- Wire selection: legacy JSON compatibility, authenticated capability upgrade, original retry identity preservation, explicit modes, and no silent downgrade or mutation replay after a Protobuf failure.
- Persistent transport reuse across concurrent calls, request serialization, malformed-reply rejection, and session disposal after cancellation.
- Lost response after execution, retry across a new MCP session using the same journal, original boot/UUID preservation, rejection after remote restart, and separate device histories.
- UTF-8 encoding, binary output preservation, invalid tool arguments rejected before transport, pending identities retained after cancellation, and upload identity retained after invalid progress.
- Actual server integration: 76800-byte binary upload/download with SHA-256, empty files, destination protection, failed download cleanup, hash-guarded edits, stdout/stderr with exit code 7, command timeout, and cancellation.

The native bridge compiles and its app bundle passes ad-hoc code-signature verification. The portable skill installer and the skill metadata are checked separately.

## Earlier physical laptop test (JSON v1)

The real stdio MCP endpoint was launched by the official Python MCP client. It listed 26 tools, authenticated over BLE, and successfully ran:

```sh
/usr/bin/sw_vers
/usr/bin/uname -m
/usr/sbin/sysctl hw.model hw.memsize hw.ncpu
```

Command submission and output polling used the persistent native BLE bridge. The job exited with code 0, returned the expected OS/hardware text, and produced no stderr. A requested folder and greeting file were then created through MCP; chunked upload, read-back, and SHA-256 verification passed. The file was retained as requested.

Repeat the read-only hardware check with:

```sh
.venv/bin/python scripts/inspect-remote.py --key /private/path/client.key
```

No key, machine-specific workspace path, journal, or captured command log is checked into the repository.

## Protobuf migration validation

The companion server passes 17 standalone checks, including both authenticated formats, binary file/command routing, cross-format retry deduplication, malformed input limits, and replay/tamper rejection. A 65536-byte upload chunk occupies 116861 bytes with JSON versus 65747 with Protobuf, including encryption and framing (43.7% fewer bytes). This measures payload size, not radio throughput.

The rebuilt native bridge completed a direct JSON request to the existing server. Subsequent live MCP attempts and a check with the unchanged JSON client both timed out. After the remote server was upgraded, authenticated automatic selection chose Protobuf. A 65536-byte binary file round-trip with SHA-256, exact stdout/stderr with exit 7, and enforced command timeout with retained output all passed over the physical BLE link. The temporary file was deleted. These physical results precede the interactive terminal feature.

## Remaining coverage

Forced radio loss mid-mutation, sleep/wake recovery, denied Bluetooth permissions, long-duration sessions, sustained throughput, Intel hardware, and older macOS versions need additional hardware testing. The durable-retry logic has deterministic tests; those are not a claim that all radio failure modes have been exercised. Claude/Codex configuration examples follow their official stdio interfaces; their individual UIs have not been end-to-end tested here.

## Interactive terminal checks

The suite now includes two real-server terminal integration tests: persistent cwd/environment, input retry identity, output text/bytes, resize/list/close, stale epochs, and input validation. The companion server has 20 standalone checks including local takeover, Ctrl+C, rolling output, and shutdown of terminal background jobs. Interactive terminal operation over the physical BLE link remains pending a server upgrade.

## Guided enrollment setup

The setup additions were checked locally with 62 MCP tests (including the six native-server integration checks) and five companion setup-helper tests. HTTP checks used loopback servers and temporary keys. Coverage includes filename/path-expression rejection, IP/port validation, bad HTTP responses and redirects, wrong file sizes, private permissions, preservation of existing keys, rollback if settings cannot be saved, and saved-key selection with explicit `--key` overrides.

An end-to-end local handoff used the packaged server initializer, the new server setup entry point and five-port prompt, actual curl download through the client enrollment prompts, automatic MCP key selection, repeated setup preserving the original key, and Ctrl+C cleanup of the repository copy. The source archive was checked to include setup helpers and exclude enrollment keys and Python caches. This setup handoff has not yet been exercised across two physical laptops or their firewall prompts.
