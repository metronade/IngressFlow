# Nginx Proxy Manager — edge configuration

NPM runs on the host, in front of this compose stack (PLAN.md §2/§3). It is the
**only** public entrypoint: `web` and `api` are reachable from the host network
(dev: published on `:3000`/`:8000`; prod: put them back behind `expose:` only
and reach them from NPM via a shared Docker network) but never directly from
the internet.

## One Proxy Host, four destinations

Create a single Proxy Host in NPM for your domain (e.g. `app.example.com`),
then split traffic by path with **Custom Locations**:

| Location | Forward to | Notes |
|---|---|---|
| `/` (default) | `web:3000` | Next.js. No special config. |
| `/api` | `api:8000` | FastAPI REST. |
| `/ws` | `api:8000` | FastAPI WebSocket endpoints. **Requires WebSockets Support** (see below). |
| `/agent` | `proxy:8889` | Residential proxy agent WebSocket (PLAN.md §4.8a). **Requires WebSockets Support.** |

Steps in the NPM UI:
1. **Proxy Hosts → Add Proxy Host**
   - Domain Names: `app.example.com`
   - Scheme: `http`, Forward Hostname/IP: `web`, Forward Port: `3000`
   - **Websockets Support: ON** (toggle on the Details tab — needed for the
     `/ws` and `/agent` locations; harmless for the rest).
2. **Custom locations** tab → add:
   - Location `/api` → Scheme `http` → Forward Hostname/IP `api` → Forward Port `8000`
   - Location `/ws` → Scheme `http` → Forward Hostname/IP `api` → Forward Port `8000`
   - Location `/agent` → Scheme `http` → Forward Hostname/IP `proxy` → Forward Port `8889`
3. **SSL tab**: request a Let's Encrypt certificate, force SSL, enable HTTP/2.
   This is the only TLS termination point in the system (PLAN.md §2) —
   containers behind it talk plain HTTP on the internal Docker network.

## Verifying the WebSocket upgrade

The API ships a plain echo endpoint at `/ws/health` (`api/app/ws/health.py`) for
exactly this purpose — it's Phase A's proof that the upgrade works end-to-end,
not the real progress hub (that's Phase C, PLAN.md §4.4).

```bash
# Direct (bypassing NPM, from inside the Docker network or with the port published):
curl http://localhost:8000/api/health

# Through NPM once the proxy host above exists:
curl https://app.example.com/api/health

# WebSocket upgrade through NPM — requires a WS client, e.g. websocat or wscat:
websocat wss://app.example.com/ws/health
> hello
< pong:hello
```

If the WS call hangs or drops immediately, re-check "Websockets Support" on
the Proxy Host — it is the most common cause of a silently failing upgrade.

## Residential proxy agents (PLAN.md §4.8a)

A residential agent (`proxy/agent.py`, running on a completely different
machine — e.g. a friend's home Docker box) connects *outbound* to
`wss://app.example.com/agent/connect`. It never needs an open port on its
own network; NPM is what makes the gateway's internal `:8889` reachable
from the public internet at all, exactly the same role it plays for `/ws`.

The `proxy` service already `expose`s `8889` on the Docker network
(`docker-compose.yml`) — nothing to change there. Just add the `/agent`
custom location from the table above to the same Proxy Host used for
everything else; there's no separate domain or TCP/Stream host needed.

Steps to actually connect a node:
1. In `/admin/proxy-nodes`, add a node — this shows a one-time token.
2. On the residential machine: `cp .env.agent.example .env.agent`, fill in
   `AGENT_TOKEN` with that token and `GATEWAY_URL=wss://app.example.com/agent/connect`.
3. `docker compose -f docker-compose.agent.yml up -d --build`.
4. Back in `/admin/proxy-nodes`, the node should flip to "connected" within
   ~10s (the page polls on that interval).

Verifying just the routing, without a real agent, the same way as `/ws/health`
above — a raw WebSocket connection through NPM should reach the gateway and
get a handshake response (an invalid/missing token closes with code 4401,
which is itself proof the connection reached the gateway):

```bash
websocat wss://app.example.com/agent/connect
{"type":"hello","token":"wrong"}
# connection closes with code 4401 ("invalid token") — NPM routing is fine,
# only the token was rejected, as expected.
```

If the connection instead hangs or drops with no response at all, re-check
"Websockets Support" on the Proxy Host and that the `/agent` location points
at `proxy:8889` (not `proxy:8888`, which is the plain-proxy port workers use
and does not speak WebSocket).
