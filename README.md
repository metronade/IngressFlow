# IngressFlow

Dockerized, open-source SaaS for public broadcasting stations to ingest
(scrape) images and video from social-media links, sort them by editorial
category, and export them as structured ZIPs — with a live dashboard, 6-hour
retention, and tiered monetization.

Full architecture, phased delivery plan, and license rationale: **[PLAN.md](PLAN.md)**.

## Status

**Phase C — Dashboard + gallery: done.** There's a real UI now: paste links,
watch them scrape live over a WebSocket, get a browser notification on
completion, then browse the results in a gallery (all / by category / by
single link), multi-select a download, or export a filtered view as a ZIP.
Retention is enforced two ways — a background sweep that hard-deletes
expired data, and a read-time gate that returns 410/closes the socket the
instant a link expires, even before the sweep runs. Verified with a real
Playwright browser clicking through the actual UI, not just curl.

Delivery phases (see [PLAN.md §9](PLAN.md#9-phased-delivery-plan) for detail):

| Phase | Scope | Status |
|---|---|---|
| A | Foundations & data model | ✅ done |
| B | Acquisition engine (parser, worker queue, proxy gateway, lawful-use gate) | ✅ done |
| C | Dashboard + gallery (realtime WS, storage, retention, export) | ✅ done |
| D | Accounts, tiers & monetization | next |
| E | Admin & observability | planned |
| F | Hardening & launch | planned |

## Architecture at a glance

- **Frontend:** Next.js (App Router) + TypeScript + Tailwind, served behind Nginx Proxy Manager (TLS + routing, host-level, not part of this compose stack — see [docs/npm-proxy-hosts.md](docs/npm-proxy-hosts.md)).
- **Backend:** FastAPI (REST + WebSocket).
- **Workers:** Celery on Redis — one task per scrape batch, iterating its links sequentially; up to 10 batches run concurrently (`--concurrency=10`). See [PLAN.md §4.2](PLAN.md#42-the-worker-queue-the-core-design).
- **Database:** PostgreSQL via SQLAlchemy 2.0 (async) + Alembic. Models live in `shared/` — the single source of truth for both `api` and `worker`.
- **Proxy:** a self-hosted rotating gateway for Tier-2 scrape traffic only; official Tier-1 platform APIs always go direct. See [PLAN.md §4.8](PLAN.md#48-self-hosted-proxy-gateway-decided--no-commercial-providers).
- **Single host** at launch; no MinIO/S3 in v1 (local disk behind a `StorageBackend` interface).

## Repository layout

```
api/        FastAPI service — scrape submit/status/cancel, share (status/media/export), WS hub
worker/     Celery worker + beat (run_batch, crash-recovery watchdog, retention sweep, cascade)
proxy/      Self-hosted rotating proxy gateway (real: CONNECT/HTTP, SOCKS5 exits, sticky sessions)
web/        Next.js frontend — input form, live dashboard, gallery (plain Tailwind, no shadcn/ui yet)
shared/     Models, parser, credential encryption, disk-layout helpers — single source of truth
docs/       Deployment/architecture reference docs
PLAN.md     Architecture & phased delivery plan
```

## Running it locally

Requires Docker + Docker Compose.

```bash
cp .env.example .env
docker compose up -d --build
```

This boots 8 containers: `web`, `api`, `worker`, `beat`, `proxy`, `flower`, `redis`, `postgres`.

Apply the database schema (first run only, or after a new migration):

```bash
docker compose exec api alembic upgrade head
```

Verify the stack is healthy:

```bash
curl http://localhost:8000/api/health
# {"status":"ok","db":"ok","redis":"ok"}
```

- Frontend: http://localhost:3000
- API: http://localhost:8000
- Flower (Celery monitoring): http://localhost:5555

In production, none of these ports are published to the host — Nginx Proxy
Manager sits in front and is the only public entrypoint (see
[docs/npm-proxy-hosts.md](docs/npm-proxy-hosts.md)).

## Using it

Open http://localhost:3000, paste links under category headers, check the
lawful-use box (required — a submission without it is rejected with 403,
[PLAN.md §4.7](PLAN.md#47-audit--lawful-use-attestation)), and submit. You're
redirected to a live dashboard, then a gallery once it finishes. The share
link (`/scrape/<token>` and `/gallery/<token>`) needs no account — it's the
same link you'd hand to someone else, valid for 6 hours
([PLAN.md §4.5](PLAN.md#45-storage-retention--share-links)).

The whole flow is also usable directly over the API (no UI required):

```bash
curl -X POST http://localhost:8000/api/scrapes \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "L1234\nhttps://www.youtube.com/watch?v=jNQXAC9IVRw",
    "config": {"include_metadata": true},
    "attestation": {"accepted": true, "text_version": "v1"}
  }'
# {"scrape_id": "...", "share_token": "...", "status": "queued", "links_total": 1}

curl http://localhost:8000/api/scrapes/<scrape_id>                      # owner-side status
curl -X POST http://localhost:8000/api/scrapes/<scrape_id>/cancel       # cooperative cancel

curl http://localhost:8000/api/share/<share_token>                      # public status
curl http://localhost:8000/api/share/<share_token>/media                # list media (add
                                                                         # ?category_id=… or ?item_id=…)
curl -OJ http://localhost:8000/api/share/<share_token>/export           # ZIP, same query filters
```

Media lands on disk at `/data/scrapes/<scrape_id>/<category>/`, exactly
matching the ZIP layout the export endpoint streams directly from.

## License

Decided: **AGPLv3 + CLA** (dual-licensing) — genuinely open source while
closing the "SaaS loophole" that lets a competitor host an unmodified copy
for free without contributing back. `LICENSE`/`CLA.md` files are not yet
added to the repo; rationale in the meantime: [PLAN.md §11](PLAN.md#11-license-recommendation).
