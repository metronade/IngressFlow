"""Residential proxy agent (§4.8a) — runs on the residential/home side.

Connects OUTBOUND to the gateway's agent WebSocket endpoint and never the
reverse, so it works behind NAT/CGNAT with zero open ports on this end. Once
authenticated, it waits for the gateway to ask it to open a connection to
some target host:port — that connection is opened from THIS network, which
is the entire point: the target site sees this network's IP, not the RZ's.
Bytes then relay in both directions over the same WebSocket, tagged with a
stream id so multiple opens over the connection's lifetime don't collide
(only one is ever concurrently active in practice — batches are processed
sequentially with one exit pinned for the whole batch, PLAN.md §4.2 — but
tagging costs nothing and removes the assumption).
"""

import asyncio
import json
import logging
import os

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("proxy-agent")

GATEWAY_URL = os.environ["GATEWAY_URL"]  # e.g. wss://proxy.example.com/agent/connect
AGENT_TOKEN = os.environ["AGENT_TOKEN"]
HEARTBEAT_INTERVAL_S = 15
RECONNECT_DELAY_S = 5
CONNECT_TIMEOUT_S = 15


async def _pump_upstream_to_ws(websocket, stream_id: str, reader: asyncio.StreamReader, streams: dict) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            await websocket.send(stream_id.encode("ascii") + chunk)
    except Exception:
        pass
    finally:
        writer = streams.pop(stream_id, None)
        if writer:
            writer.close()
        try:
            await websocket.send(json.dumps({"type": "close", "stream_id": stream_id}))
        except Exception:
            pass


async def _handle_open(websocket, streams: dict, event: dict) -> None:
    stream_id = event["stream_id"]
    host, port = event["host"], event["port"]
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=CONNECT_TIMEOUT_S)
    except Exception as exc:
        await websocket.send(json.dumps({"type": "error", "stream_id": stream_id, "message": str(exc)}))
        return

    streams[stream_id] = writer
    await websocket.send(json.dumps({"type": "opened", "stream_id": stream_id}))
    asyncio.ensure_future(_pump_upstream_to_ws(websocket, stream_id, reader, streams))


async def _handle_data(stream_id: str, payload: bytes, streams: dict) -> None:
    writer = streams.get(stream_id)
    if writer is None:
        return
    try:
        writer.write(payload)
        await writer.drain()
    except Exception:
        streams.pop(stream_id, None)


async def _handle_close(stream_id: str, streams: dict) -> None:
    writer = streams.pop(stream_id, None)
    if writer:
        writer.close()


async def _heartbeat_loop(websocket) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        await websocket.send(json.dumps({"type": "heartbeat"}))


async def _run_once() -> None:
    streams: dict[str, asyncio.StreamWriter] = {}
    async with websockets.connect(GATEWAY_URL) as websocket:
        await websocket.send(json.dumps({"type": "hello", "token": AGENT_TOKEN}))
        ack_raw = await asyncio.wait_for(websocket.recv(), timeout=10)
        ack = json.loads(ack_raw)
        if ack.get("type") != "hello-ack":
            raise ConnectionError(f"unexpected handshake response: {ack}")
        logger.info("connected and authenticated to %s", GATEWAY_URL)

        heartbeat_task = asyncio.ensure_future(_heartbeat_loop(websocket))
        try:
            async for message in websocket:
                if isinstance(message, (bytes, bytearray)):
                    stream_id = bytes(message[:32]).decode("ascii")
                    await _handle_data(stream_id, bytes(message[32:]), streams)
                    continue
                event = json.loads(message)
                etype = event.get("type")
                if etype == "open":
                    asyncio.ensure_future(_handle_open(websocket, streams, event))
                elif etype == "close":
                    await _handle_close(event["stream_id"], streams)
        finally:
            heartbeat_task.cancel()
            for writer in streams.values():
                writer.close()


async def main() -> None:
    while True:
        try:
            await _run_once()
        except Exception:
            logger.exception("connection lost — reconnecting in %ds", RECONNECT_DELAY_S)
        await asyncio.sleep(RECONNECT_DELAY_S)


if __name__ == "__main__":
    asyncio.run(main())
