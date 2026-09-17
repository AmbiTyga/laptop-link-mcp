import asyncio
import sys

import pytest

from laptop_link_mcp.bridge import BridgeTransport

BRIDGE = """
import json, os, sys, time
for line in sys.stdin:
    request = json.loads(line)
    if request['method'] == 'hang': time.sleep(60)
    if request['method'] == 'bad':
        print('{}', flush=True)
        continue
    print(json.dumps({'version': 1, 'id': request['id'], 'bootID': 'test-boot',
                      'result': {'pid': os.getpid()}}), flush=True)
"""


async def test_persistent_transport_serializes_concurrent_calls():
    transport = BridgeTransport([sys.executable, "-u", "-c", BRIDGE])
    try:
        results = await asyncio.gather(*(transport.exchange({"id": str(i), "method": "ok"})
                                         for i in range(8)))
        assert [r["id"] for r in results] == [str(i) for i in range(8)]
        assert len({r["result"]["pid"] for r in results}) == 1
    finally:
        await transport.close()


async def test_cancel_discards_session_and_does_not_consume_late_reply():
    transport = BridgeTransport([sys.executable, "-u", "-c", BRIDGE])
    original = await transport.exchange({"id": "first", "method": "ok"})
    task = asyncio.create_task(transport.exchange({"id": "cancelled", "method": "hang"}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.process is None
    try:
        recovered = await transport.exchange({"id": "next", "method": "ok"})
        assert recovered["id"] == "next"
        assert recovered["result"]["pid"] != original["result"]["pid"]
    finally:
        await transport.close()


async def test_malformed_response_closes_transport():
    transport = BridgeTransport([sys.executable, "-u", "-c", BRIDGE])
    with pytest.raises(ConnectionError, match="Invalid BLE response"):
        await transport.exchange({"id": "x", "method": "bad"})
    assert transport.process is None
