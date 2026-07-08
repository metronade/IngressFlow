# IngressFlow

Dockerized, open-source SaaS for public broadcasting stations to ingest
(scrape) images and video from social-media links, sort them by editorial
category, and export them as structured ZIPs — with a live dashboard, 6-hour
retention, and tiered monetization.

Full architecture, phased delivery plan, and license rationale: **[PLAN.md](PLAN.md)**.

## Status

**Phase B — Acquisition engine: done.** A scrape batch runs end to end —
parsed, gated behind a mandatory lawful-use attestation, processed
sequentially through a real yt-dlp → gallery-dl → Playwright cascade behind
a self-hosted rotating proxy gateway, checkpointed to Postgres with
checksum dedup, audit-logged, cancellable, and resumable if the worker
crashes mid-batch. All verified against real content via Docker, not mocks.

Delivery phases (see [PLAN.md §9](PLAN.md#9-phased-delivery-plan) for detail):

| Phase | Scope | Status |
|---|---|---|
| A | Foundations & data model | ✅ done |
| B | Acquisition engine (parser, worker queue, proxy gateway, lawful-use gate) | ✅ done |
| C | Dashboard + gallery (realtime WS, storage, retention, export) | next |
| D | Accounts, tiers & monetization | planned |
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
api/        FastAPI service (REST, WebSocket, Alembic migrations, scrape submit/status/cancel)
worker/     Celery worker + beat (run_batch, crash-recovery watchdog, scraping cascade)
proxy/      Self-hosted rotating proxy gateway (real: CONNECT/HTTP, SOCKS5 exits, sticky sessions)
web/        Next.js frontend
shared/     Models, category-header parser, credential encryption — single source of truth
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

## Submitting a scrape

No UI yet (Phase C) — the acquisition engine is fully usable over the API.
The lawful-use attestation is mandatory; a submission without `accepted: true`
is rejected with 403 ([PLAN.md §4.7](PLAN.md#47-audit--lawful-use-attestation)):

```bash
curl -X POST http://localhost:8000/api/scrapes \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "L1234\nhttps://www.youtube.com/watch?v=jNQXAC9IVRw",
    "config": {"include_metadata": true},
    "attestation": {"accepted": true, "text_version": "v1"}
  }'
# {"scrape_id": "...", "share_token": "...", "status": "queued", "links_total": 1}

curl http://localhost:8000/api/scrapes/<scrape_id>       # poll status + per-item results
curl -X POST http://localhost:8000/api/scrapes/<scrape_id>/cancel   # cooperative cancel
```

Media lands on disk at `/data/scrapes/<scrape_id>/<category>/`, matching the
ZIP layout Phase C will export directly.

## License

Decided: **AGPLv3 + CLA** (dual-licensing) — genuinely open source while
closing the "SaaS loophole" that lets a competitor host an unmodified copy
for free without contributing back. `LICENSE`/`CLA.md` files are not yet
added to the repo; rationale in the meantime: [PLAN.md §11](PLAN.md#11-license-recommendation).
