# Self-hosted proxy gateway — attaching real exits

Background and the "residential" caveat: [PLAN.md §4.8](../PLAN.md#48-self-hosted-proxy-gateway-decided--no-commercial-providers).

## Default: zero exits

Out of the box, `proxy/exits.yml` (baked into the image from
`exits.example.yml`) is an empty list. With zero — or zero *healthy* — exits,
the gateway falls back to **direct passthrough**: Tier-2 scrape traffic exits
through the container's own network stack, i.e. the host's IP. This is a
deliberate, honest default: a Docker container cannot manufacture residential
IPs on its own, so v1 doesn't pretend to.

## Attaching a real exit

An exit is any SOCKS5 endpoint you control — a mobile LTE modem/dongle, a
home connection, or a self-hosted SOCKS5/VPN exit. To attach one without
editing the image:

1. Create `proxy/exits.yml` on the host (gitignored — this is operator
   infrastructure, not something to commit):

   ```yaml
   exits:
     - name: lte-modem-1
       host: 192.168.1.50
       port: 1080
       # username: user       # optional, SOCKS5 auth
       # password: pass
   ```

2. Add a `docker-compose.override.yml` (Compose merges this automatically):

   ```yaml
   services:
     proxy:
       volumes:
         - ./proxy/exits.yml:/app/exits.yml:ro
   ```

3. `docker compose up -d proxy` — the gateway loads the file at startup.

## How rotation and pinning work

- Every 30s, the gateway health-checks each configured exit (a SOCKS5 CONNECT
  to a known-good host). Unhealthy exits drop out of rotation automatically.
- Each **batch** (one scrape) gets a sticky session, encoded as the proxy
  username (`session-<scrape_id>`) — the same convention real rotating-proxy
  providers use. The gateway pins one healthy exit to that session for the
  whole batch, matching the anti-block design of processing a batch's links
  sequentially on one identity ([PLAN.md §4.2](../PLAN.md#42-the-worker-queue-the-core-design)).
  If that exit goes unhealthy mid-batch, the session gets reassigned to
  another healthy exit (or to direct passthrough, if none remain).

## Checking gateway state

```bash
curl http://localhost:8888/health   # {"status": "ok"}   — only reachable from inside the compose network
docker compose exec worker curl -s http://proxy:8888/stats
```

`/stats` reports each exit's health and, per session, bytes transferred and
which exit (if any) it's pinned to.
