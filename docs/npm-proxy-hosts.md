# Nginx Proxy Manager — edge configuration

NPM runs on the host, in front of this compose stack (PLAN.md §2/§3). It is the
**only** public entrypoint: `web` and `api` are reachable from the host network
(dev: published on `:3000`/`:8000`; prod: put them back behind `expose:` only
and reach them from NPM via a shared Docker network) but never directly from
the internet.

## One Proxy Host, three destinations

Create a single Proxy Host in NPM for your domain (e.g. `app.example.com`),
then split traffic by path with **Custom Locations**:

| Location | Forward to | Notes |
|---|---|---|
| `/` (default) | `web:3000` | Next.js. No special config. |
| `/api` | `api:8000` | FastAPI REST. |
| `/ws` | `api:8000` | FastAPI WebSocket endpoints. **Requires WebSockets Support** (see below). |

Steps in the NPM UI:
1. **Proxy Hosts → Add Proxy Host**
   - Domain Names: `app.example.com`
   - Scheme: `http`, Forward Hostname/IP: `web`, Forward Port: `3000`
   - **Websockets Support: ON** (toggle on the Details tab — needed for the
     `/ws` location; harmless for the rest).
2. **Custom locations** tab → add:
   - Location `/api` → Scheme `http` → Forward Hostname/IP `api` → Forward Port `8000`
   - Location `/ws` → Scheme `http` → Forward Hostname/IP `api` → Forward Port `8000`
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
