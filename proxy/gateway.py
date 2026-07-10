"""Self-hosted rotating proxy gateway (PLAN.md §4.8, §4.8a).

A minimal asyncio HTTP/CONNECT forward proxy used only by the Tier-2 scrape
path — Tier-1 API calls always go direct (resolver.py / PLAN.md §4.8's
egress table never routes them here). Exit-IP rotation, per-batch sticky
sessions (encoded as the Proxy-Authorization username, the way commercial
rotating-proxy providers do it), health-check eviction, and bandwidth
metering — all built to run correctly with *zero* exits configured, which
degrades to plain direct passthrough through the host's own IP (the honest
default for v1, §4.8).

§4.8a adds a second exit kind alongside the static (dial-out) exits.yml
ones: self-registering "agent" nodes — a home/residential Docker container
that dials *this* gateway (never the reverse, so it works behind NAT/CGNAT
with zero open ports on its end) over a WebSocket, on a separate internal
port from the plain proxy traffic. Both exit kinds share one priority-
ordered pool and one circuit-breaker failover policy; `open_upstream`
branches on `exit_.kind` but nothing else downstream (the pipe/relay loop)
needed to change at all.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import websockets
import yaml
from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy as SocksProxy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("proxy-gateway")

EXITS_FILE = os.environ.get("EXITS_FILE", "/app/exits.yml")
HEALTHCHECK_INTERVAL_S = 30
HEALTHCHECK_HOST, HEALTHCHECK_PORT = "1.1.1.1", 443
LISTEN_PORT = 8888
AGENT_WS_PORT = 8889
CONNECT_TIMEOUT_S = 15
INTERNAL_SECRET = os.environ.get("PROXY_INTERNAL_SECRET", "")

FAILURE_THRESHOLD = 3  # consecutive failed CONNECTs before a node is demoted
COOLDOWN_S = 120  # how long a demoted node sits out before being retried


@dataclass
class Exit:
    """One candidate egress — either a static dial-out SOCKS5 endpoint
    (exits.yml) or a live self-registered agent (§4.8a). Priority and the
    failure/cooldown circuit breaker are shared by both kinds."""

    name: str
    kind: str = "dial"  # "dial" | "agent"
    priority: int = 100  # lower is tried first
    healthy: bool = True  # dial: periodic TCP check; agent: websocket currently open
    consecutive_failures: int = 0
    demoted_until: float = 0.0  # time.monotonic() deadline; 0 = not demoted
    # dial-only:
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    # agent-only:
    node_id: str | None = None
    agent: "AgentSession | None" = None


@dataclass
class SessionStats:
    bytes_up: int = 0
    bytes_down: int = 0
    requests: int = 0
    exit_name: str | None = None


class AgentStream:
    """Duck-types just enough of asyncio's StreamReader/StreamWriter for
    Gateway._pipe() to use unmodified: read()/write()/drain()/close(). Bytes
    actually travel as binary WebSocket frames over the agent's one control
    connection, tagged with this stream's id."""

    def __init__(self, agent: "AgentSession", stream_id: str):
        self.agent = agent
        self.stream_id = stream_id
        self._incoming: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._pending_writes: list[bytes] = []
        self._opened_event = asyncio.Event()
        self._open_error: str | None = None
        self._closed = False

    def mark_opened(self) -> None:
        self._opened_event.set()

    def mark_error(self, message: str) -> None:
        self._open_error = message
        self._opened_event.set()

    async def wait_opened(self) -> None:
        await self._opened_event.wait()
        if self._open_error:
            raise ConnectionError(self._open_error)

    def feed(self, data: bytes | None) -> None:
        """Called by the agent's receive loop when a data/close frame for
        this stream arrives. None means the stream closed from the agent
        side."""
        self._incoming.put_nowait(data)

    async def read(self, _n: int = 65536) -> bytes:
        if self._closed:
            return b""
        chunk = await self._incoming.get()
        if chunk is None:
            self._closed = True
            return b""
        return chunk

    def write(self, data: bytes) -> None:
        self._pending_writes.append(data)

    async def drain(self) -> None:
        while self._pending_writes:
            chunk = self._pending_writes.pop(0)
            await self.agent.send_data(self.stream_id, chunk)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        asyncio.ensure_future(self.agent.send_close(self.stream_id))


class AgentSession:
    """One connected residential agent's control channel."""

    def __init__(self, node_id: str, name: str, websocket) -> None:
        self.node_id = node_id
        self.name = name
        self.websocket = websocket
        self.streams: dict[str, AgentStream] = {}
        self.bytes_relayed = 0
        self.connected_at = time.time()

    async def open_stream(self, host: str, port: int) -> AgentStream:
        stream_id = uuid.uuid4().hex  # fixed 32 hex chars — used as a length-prefix-free frame tag
        stream = AgentStream(self, stream_id)
        self.streams[stream_id] = stream
        await self.websocket.send(json.dumps({"type": "open", "stream_id": stream_id, "host": host, "port": port}))
        try:
            await asyncio.wait_for(stream.wait_opened(), timeout=CONNECT_TIMEOUT_S)
        except (TimeoutError, ConnectionError):
            self.streams.pop(stream_id, None)
            raise
        return stream

    async def send_data(self, stream_id: str, data: bytes) -> None:
        self.bytes_relayed += len(data)
        await self.websocket.send(stream_id.encode("ascii") + data)

    async def send_close(self, stream_id: str) -> None:
        self.streams.pop(stream_id, None)
        try:
            await self.websocket.send(json.dumps({"type": "close", "stream_id": stream_id}))
        except Exception:
            pass  # connection may already be gone — nothing to clean up on our end

    async def receive_loop(self, gateway: "Gateway") -> None:
        try:
            async for message in self.websocket:
                if isinstance(message, (bytes, bytearray)):
                    stream_id = bytes(message[:32]).decode("ascii")
                    stream = self.streams.get(stream_id)
                    if stream:
                        stream.feed(bytes(message[32:]))
                    continue

                event = json.loads(message)
                stream_id = event.get("stream_id")
                stream = self.streams.get(stream_id) if stream_id else None
                etype = event.get("type")
                if etype == "opened" and stream:
                    stream.mark_opened()
                elif etype == "error" and stream:
                    stream.mark_error(event.get("message", "agent-reported error"))
                elif etype == "close" and stream:
                    stream.feed(None)
                    self.streams.pop(stream_id, None)
                elif etype == "heartbeat":
                    gateway.note_heartbeat(self.node_id)
        finally:
            for stream in list(self.streams.values()):
                stream.mark_error("agent disconnected")
                stream.feed(None)
            gateway.on_agent_disconnected(self.node_id)


class Gateway:
    def __init__(self) -> None:
        self.exits: list[Exit] = []
        self.session_exit: dict[str, Exit | None] = {}
        self.stats: dict[str, SessionStats] = {}
        self._rr = 0
        # node_id -> {"name", "token_hash", "priority", "enabled"} — pushed by
        # the api service after any admin change to ProxyNode rows.
        self.node_allowlist: dict[str, dict] = {}
        self.last_seen: dict[str, float] = {}

    # -- static (exits.yml) exit pool --------------------------------------

    def load_exits(self) -> None:
        if not os.path.exists(EXITS_FILE):
            logger.info("no exits file at %s — direct passthrough only", EXITS_FILE)
            return
        with open(EXITS_FILE) as f:
            data = yaml.safe_load(f) or {}
        dial_exits = [
            Exit(
                name=e["name"],
                kind="dial",
                priority=int(e.get("priority", 100)),
                host=e["host"],
                port=int(e["port"]),
                username=e.get("username"),
                password=e.get("password"),
            )
            for e in data.get("exits", [])
        ]
        self.exits = dial_exits + [e for e in self.exits if e.kind == "agent"]
        logger.info("loaded %d dial exit(s) from %s", len(dial_exits), EXITS_FILE)

    # -- agent (§4.8a) exit pool --------------------------------------------

    def sync_nodes(self, nodes: list[dict]) -> None:
        """Replaces the admin-managed node allowlist. Disconnects any live
        agent whose node was disabled or removed — an admin toggle is
        effective immediately, not just for the next new connection."""
        self.node_allowlist = {n["id"]: n for n in nodes}
        for exit_ in self.exits:
            if exit_.kind == "agent" and exit_.node_id in self.node_allowlist:
                exit_.priority = int(self.node_allowlist[exit_.node_id].get("priority", 100))

        for node_id, session in list(self._live_agents().items()):
            node = self.node_allowlist.get(node_id)
            if node is None or not node.get("enabled", True):
                logger.info("node %s disabled/removed — disconnecting", session.name)
                asyncio.ensure_future(session.websocket.close(code=4403, reason="node disabled"))

    def _live_agents(self) -> dict[str, AgentSession]:
        return {e.node_id: e.agent for e in self.exits if e.kind == "agent" and e.agent is not None}

    def match_token(self, token: str) -> dict | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        for node_id, node in self.node_allowlist.items():
            if node.get("token_hash") == token_hash:
                return {**node, "id": node_id}
        return None

    def note_heartbeat(self, node_id: str) -> None:
        self.last_seen[node_id] = time.time()

    def on_agent_disconnected(self, node_id: str) -> None:
        for exit_ in self.exits:
            if exit_.kind == "agent" and exit_.node_id == node_id:
                exit_.healthy = False
                exit_.agent = None

    async def handle_agent_connection(self, websocket) -> None:
        node_id = None
        try:
            hello_raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            hello = json.loads(hello_raw)
            if hello.get("type") != "hello" or not hello.get("token"):
                await websocket.close(code=4401, reason="expected hello with token")
                return

            node = self.match_token(hello["token"])
            if node is None:
                await websocket.close(code=4401, reason="invalid token")
                return
            if not node.get("enabled", True):
                await websocket.close(code=4403, reason="node disabled")
                return

            node_id = node["id"]
            if any(e.kind == "agent" and e.node_id == node_id and e.agent is not None for e in self.exits):
                await websocket.close(code=4409, reason="node already connected")
                return

            session = AgentSession(node_id, node["name"], websocket)
            existing = next((e for e in self.exits if e.kind == "agent" and e.node_id == node_id), None)
            if existing is None:
                existing = Exit(name=node["name"], kind="agent", node_id=node_id)
                self.exits.append(existing)
            existing.priority = int(node.get("priority", 100))
            existing.agent = session
            existing.healthy = True
            existing.consecutive_failures = 0
            existing.demoted_until = 0.0
            self.note_heartbeat(node_id)

            await websocket.send(json.dumps({"type": "hello-ack"}))
            logger.info("agent node connected: %s (%s)", node["name"], node_id)
            await session.receive_loop(self)
            logger.info("agent node disconnected: %s (%s)", node["name"], node_id)
        except (TimeoutError, ConnectionError, json.JSONDecodeError):
            pass
        except Exception:
            logger.exception("agent connection error")

    # -- exit selection: priority + circuit breaker ------------------------

    def _usable(self, exit_: Exit) -> bool:
        if not exit_.healthy:
            return False
        if exit_.demoted_until and time.monotonic() < exit_.demoted_until:
            return False
        return True

    def assign_exit(self, session_id: str) -> "Exit | None":
        current = self.session_exit.get(session_id)
        if current is not None and self._usable(current):
            return current

        usable = [e for e in self.exits if self._usable(e)]
        if not usable:
            self.session_exit[session_id] = None
            return None

        best_priority = min(e.priority for e in usable)
        tier = [e for e in usable if e.priority == best_priority]
        chosen = tier[self._rr % len(tier)]
        self._rr += 1
        self.session_exit[session_id] = chosen
        return chosen

    def report_result(self, exit_: "Exit | None", success: bool) -> None:
        if exit_ is None:
            return
        if success:
            exit_.consecutive_failures = 0
            exit_.demoted_until = 0.0
            return
        exit_.consecutive_failures += 1
        if exit_.consecutive_failures >= FAILURE_THRESHOLD:
            exit_.demoted_until = time.monotonic() + COOLDOWN_S
            logger.warning(
                "exit %s demoted for %ds after %d consecutive failures",
                exit_.name, COOLDOWN_S, exit_.consecutive_failures,
            )

    async def health_check_loop(self) -> None:
        while True:
            for exit_ in list(self.exits):
                if exit_.kind == "dial":
                    exit_.healthy = await self._check_one(exit_)
                # agent exits: healthy is driven by connect/disconnect events,
                # not a periodic external check — "healthy" means "the
                # control channel is actually open right now".
            await asyncio.sleep(HEALTHCHECK_INTERVAL_S)

    async def _check_one(self, exit_: Exit) -> bool:
        try:
            _reader, writer = await asyncio.wait_for(
                self.open_upstream(exit_, HEALTHCHECK_HOST, HEALTHCHECK_PORT), timeout=8
            )
            writer.close()
            return True
        except Exception:
            logger.warning("exit %s failed health check", exit_.name)
            return False

    # -- connecting through an exit (or direct) ---------------------------

    async def open_upstream(self, exit_: "Exit | None", host: str, port: int):
        if exit_ is None:
            return await asyncio.open_connection(host, port)
        if exit_.kind == "agent":
            if exit_.agent is None:
                raise ConnectionError(f"agent {exit_.name} not connected")
            stream = await exit_.agent.open_stream(host, port)
            return stream, stream
        proxy = SocksProxy(
            proxy_type=ProxyType.SOCKS5,
            host=exit_.host,
            port=exit_.port,
            username=exit_.username,
            password=exit_.password,
        )
        sock = await proxy.connect(dest_host=host, dest_port=port, timeout=CONNECT_TIMEOUT_S)
        return await asyncio.open_connection(sock=sock)

    # -- request handling (plain proxy port, workers only) -----------------

    def _session_stats(self, session_id: str) -> SessionStats:
        return self.stats.setdefault(session_id, SessionStats())

    def _session_id(self, headers: dict) -> str:
        auth = headers.get("proxy-authorization", "")
        if auth.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("latin-1")
                return decoded.split(":", 1)[0]
            except Exception:
                pass
        return "default"

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                return
            method, target, _version = request_line.decode("latin-1").strip().split(" ", 2)

            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10)
                if line in (b"\r\n", b""):
                    break
                if b":" in line:
                    k, v = line.decode("latin-1").split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            if method == "CONNECT":
                await self._handle_connect(target, headers, reader, writer)
            elif method == "POST" and target.startswith("/internal/"):
                body_len = int(headers.get("content-length", "0"))
                body = await reader.readexactly(body_len) if body_len else b""
                await self._handle_internal(target, headers, body, writer)
            elif target.startswith("http://") or target.startswith("https://"):
                await self._handle_forward(method, target, headers, reader, writer)
            else:
                await self._handle_local(target, writer)
        except (TimeoutError, ConnectionError, ValueError):
            pass
        except Exception:
            logger.exception("unhandled error serving request")
        finally:
            writer.close()

    async def _handle_connect(self, target: str, headers: dict, reader, writer) -> None:
        host, _, port_s = target.partition(":")
        port = int(port_s or 443)
        session_id = self._session_id(headers)
        exit_ = self.assign_exit(session_id)
        stats = self._session_stats(session_id)
        stats.exit_name = exit_.name if exit_ else None
        stats.requests += 1

        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                self.open_upstream(exit_, host, port), timeout=CONNECT_TIMEOUT_S
            )
        except Exception:
            self.report_result(exit_, success=False)
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            return

        self.report_result(exit_, success=True)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await self._pipe(reader, writer, upstream_reader, upstream_writer, stats)

    async def _handle_forward(self, method: str, target: str, headers: dict, reader, writer) -> None:
        parts = urlsplit(target)
        host, port = parts.hostname, parts.port or 80
        session_id = self._session_id(headers)
        exit_ = self.assign_exit(session_id)
        stats = self._session_stats(session_id)
        stats.exit_name = exit_.name if exit_ else None
        stats.requests += 1

        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                self.open_upstream(exit_, host, port), timeout=CONNECT_TIMEOUT_S
            )
        except Exception:
            self.report_result(exit_, success=False)
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            return

        self.report_result(exit_, success=True)
        path = parts.path or "/"
        if parts.query:
            path += f"?{parts.query}"
        headers.pop("proxy-authorization", None)
        headers.pop("proxy-connection", None)

        request = f"{method} {path} HTTP/1.1\r\n"
        for k, v in headers.items():
            request += f"{k}: {v}\r\n"
        request += "\r\n"
        upstream_writer.write(request.encode("latin-1"))
        stats.bytes_up += len(request)
        await upstream_writer.drain()

        await self._pipe(reader, writer, upstream_reader, upstream_writer, stats)

    async def _handle_local(self, target: str, writer) -> None:
        if target == "/health":
            body = b'{"status":"ok"}'
        elif target == "/stats":
            body = self._stats_json().encode()
        else:
            writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
            await writer.drain()
            return
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        await writer.drain()

    async def _handle_internal(self, target: str, headers: dict, body: bytes, writer) -> None:
        """Admin-only control surface, called by the api service — never
        reachable from outside the Docker network (proxy's port is `expose`d
        only). Still shared-secret gated in case that ever changes."""
        if headers.get("x-internal-secret") != INTERNAL_SECRET or not INTERNAL_SECRET:
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            return

        if target == "/internal/nodes/sync":
            try:
                nodes = json.loads(body).get("nodes", [])
            except json.JSONDecodeError:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await writer.drain()
                return
            self.sync_nodes(nodes)
            resp = b'{"status":"ok"}'
        else:
            writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
            await writer.drain()
            return

        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(resp)).encode()
            + b"\r\n\r\n"
            + resp
        )
        await writer.drain()

    def _stats_json(self) -> str:
        return json.dumps(
            {
                "exits": [
                    {
                        "name": e.name,
                        "kind": e.kind,
                        "node_id": e.node_id,
                        "priority": e.priority,
                        "healthy": e.healthy,
                        "demoted": bool(e.demoted_until and time.monotonic() < e.demoted_until),
                        "consecutive_failures": e.consecutive_failures,
                        "bytes_relayed": e.agent.bytes_relayed if e.agent else None,
                        "last_seen_at": self.last_seen.get(e.node_id) if e.node_id else None,
                    }
                    for e in self.exits
                ],
                "sessions": {
                    sid: {
                        "bytes_up": s.bytes_up,
                        "bytes_down": s.bytes_down,
                        "requests": s.requests,
                        "exit": s.exit_name,
                    }
                    for sid, s in self.stats.items()
                },
            }
        )

    async def _pipe(self, client_reader, client_writer, upstream_reader, upstream_writer, stats: SessionStats) -> None:
        async def relay(src, dst, counter_attr: str):
            try:
                while True:
                    chunk = await src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
                    await dst.drain()
                    setattr(stats, counter_attr, getattr(stats, counter_attr) + len(chunk))
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                dst.close()

        await asyncio.gather(
            relay(client_reader, upstream_writer, "bytes_up"),
            relay(upstream_reader, client_writer, "bytes_down"),
        )


gateway = Gateway()


async def main() -> None:
    gateway.load_exits()
    asyncio.create_task(gateway.health_check_loop())

    proxy_server = await asyncio.start_server(gateway.handle, "0.0.0.0", LISTEN_PORT)
    logger.info("proxy gateway listening on :%d", LISTEN_PORT)

    async with websockets.serve(gateway.handle_agent_connection, "0.0.0.0", AGENT_WS_PORT):
        logger.info("agent WS listener on :%d", AGENT_WS_PORT)
        async with proxy_server:
            await proxy_server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
