import argparse
import asyncio
import hashlib
import os
import stat
import sys
from contextlib import suppress
from pathlib import Path

from mcp.server.stdio import stdio_server

from .tools import create_server
from .request_store import Journal
from .session import Remote
from .wire_transport import WireTransport


def configuration():
    parser = argparse.ArgumentParser(description="MCP tools for the remote Laptop Link (stdio transport)")
    parser.add_argument("--key", type=Path, required=True, help="Private 32-byte enrollment key file")
    parser.add_argument("--bridge", type=Path, required=True, help="Absolute path to built link-bridge executable")
    parser.add_argument("--name", help="Optional advertised BLE name filter; identity is authenticated by the key")
    parser.add_argument("--wire", choices=["auto", "protobuf", "json"], default="auto",
                        help="BLE format: auto prefers authenticated Protobuf support; json supports older servers")
    parser.add_argument("--timeout", type=int, default=120, help="Per-BLE-RPC timeout, not command execution timeout")
    parser.add_argument("--state-dir", type=Path,
                        default=Path.home() / "Library/Application Support/LaptopLinkMCP")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be between 1 and 3600 seconds")
    args.bridge = args.bridge.expanduser().resolve()
    args.key = args.key.expanduser().absolute()
    args.state_dir = args.state_dir.expanduser().absolute()
    if not args.bridge.is_file() or not os.access(args.bridge, os.X_OK):
        parser.error("--bridge must be an executable; run scripts/build-bridge.sh")
    key_info = args.key.stat()
    if not stat.S_ISREG(key_info.st_mode) or key_info.st_uid != os.getuid() or key_info.st_mode & 0o077:
        parser.error("Key must be a regular file owned by you with private permissions (chmod 600)")
    key = args.key.read_bytes()
    if len(key) != 32:
        parser.error("Enrollment key must be exactly 32 bytes")
    # Scope journals to the key and device selection, never log key material.
    args.scope = hashlib.sha256(key + b"\0" + (args.name or "").encode()).hexdigest()
    return args


async def serve(args):
    command = [str(args.bridge), "--key", str(args.key), "--timeout", str(args.timeout)]
    if args.name:
        command += ["--name", args.name]
    journal = Journal(args.state_dir, args.scope)
    transport = WireTransport(command, args.timeout, args.wire)
    remote = Remote(transport, journal)
    server = create_server(remote)
    heartbeat = asyncio.create_task(remote.keepalive())
    try:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await transport.close()
        journal.close()


def main():
    try:
        asyncio.run(serve(configuration()))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError) as exc:
        print(f"laptop-link-mcp: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
