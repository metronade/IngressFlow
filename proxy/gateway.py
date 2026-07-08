"""Self-hosted rotating proxy gateway (PLAN.md §4.8).

A minimal asyncio HTTP/CONNECT forward proxy used only by the Tier-2 scrape
path — Tier-1 API calls always go direct (resolver.py / PLAN.md §4.8's
egress table never routes them here). Exit-IP rotation, per-batch sticky
sessions (encoded as the Proxy-Authorization username, the way commercial
rotating-proxy providers do it), health-check eviction, and bandwidth
metering — all built to run correctly with *zero* exits configured, which
degrades to plain direct passthrough through the host's own IP (the honest
default for v1, §4.8).
"""

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import yaml
from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy as SocksProxy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("proxy-gateway")

EXITS_FILE = os.environ.get("EXITS_FILE", "/app/exits.yml")
HEALTHCHECK_INTERVAL_S = 30
HEALTHCHECK_HOST, HEALTHCHECK_PORT = "1.1.1.1", 443
LISTEN_PORT = 8888
CONNECT_TIMEOUT_S = 15


@dataclass
class Exit:
    name: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    healthy: bool = True


@dataclass
class SessionStats:
    bytes_up: int = 0
    bytes_down: int = 0
    requests: int = 0
    exit_name: str | None = None


class Gateway:
    def __init__(self) -> None:
        self.exits: list[Exit] = []
        self.session_exit: dict[str, Exit | None] = {}
        self.stats: dict[str, SessionStats] = {}
        self._rr = 0

    # -- exit pool -------------------------------------------------------

    def load_exits(self) -> None:
        if not os.path.exists(EXITS_FILE):
            logger.info("no exits file at %s — direct passthrough only", EXITS_FILE)
            self.exits = []
            return
        with open(EXITS_FILE) as f:
            data = yaml.safe_load(f) or {}
        self.exits = [
            Exit(
                name=e["name"],
                host=e["host"],
                port=int(e["port"]),
                username=e.get("username"),
                password=e.get("password"),
            )
            for e in data.get("exits", [])
        ]
        logger.info("loaded %d exit(s) from %s", len(self.exits), EXITS_FILE)

    def healthy_exits(self) -> list[Exit]:
        return [e for e in self.exits if e.healthy]

    def assign_exit(self, session_id: str) -> "Exit | None":
        current = self.session_exit.get(session_id)
        if current is not None and current.healthy:
            return current
        healthy = self.healthy_exits()
        if not healthy:
            self.session_exit[session_id] = None
            return None
        chosen = healthy[self._rr % len(healthy)]
        self._rr += 1
        self.session_exit[session_id] = chosen
        return chosen

    async def health_check_loop(self) -> None:
        while True:
            for exit_ in list(self.exits):
                exit_.healthy = await self._check_one(exit_)
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
        proxy = SocksProxy(
            proxy_type=ProxyType.SOCKS5,
            host=exit_.host,
            port=exit_.port,
            username=exit_.username,
            password=exit_.password,
        )
        sock = await proxy.connect(dest_host=host, dest_port=port, timeout=CONNECT_TIMEOUT_S)
        return await asyncio.open_connection(sock=sock)

    # -- request handling --------------------------------------------------

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
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            return

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
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            return

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

    def _stats_json(self) -> str:
        return json.dumps(
            {
                "exits": [{"name": e.name, "healthy": e.healthy} for e in self.exits],
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
    server = await asyncio.start_server(gateway.handle, "0.0.0.0", LISTEN_PORT)
    logger.info("proxy gateway listening on :%d", LISTEN_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
