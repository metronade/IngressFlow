# IngressFlow

Dockerized, open-source SaaS for public broadcasting stations to ingest
(scrape) images and video from social-media links, sort them by editorial
category, and export them as structured ZIPs — with a live dashboard, 6-hour
retention, and tiered monetization.

Full architecture, phased delivery plan, and license rationale: **[PLAN.md](PLAN.md)**.

## Status

**Phase E — Admin & observability: done.** There's now an admin panel at
`/admin` (gated by `is_superuser`, seeded via `ADMIN_BOOTSTRAP_EMAIL` since
there's no other way to create the first one): live CPU/memory/disk,
the disk-full forecast, proxy gateway health, a `Setting`-table editor for
tier limits/retention/the proxy kill-switch, a `PlatformCredential` manager
that actually flips a platform from Tier-2 scrape to Tier-1 API routing the
moment a credential is enabled, an editable CMS for legal pages (public at
`/legal/<slug>`), an audit-log viewer, and per-platform success/fallback-mix
health. Flower is now behind basic auth.

Delivery phases (see [PLAN.md §9](PLAN.md#9-phased-delivery-plan) for detail):

| Phase | Scope | Status |
|---|---|---|
| A | Foundations & data model | ✅ done |
| B | Acquisition engine (parser, worker queue, proxy gateway, lawful-use gate) | ✅ done |
| C | Dashboard + gallery (realtime WS, storage, retention, export) | ✅ done |
| D | Accounts, tiers & monetization | ✅ done |
| E | Admin & observability | ✅ done |
| F | Hardening & launch | next |

## Architecture at a glance

- **Frontend:** Next.js (App Router) + TypeScript + Tailwind, served behind Nginx Proxy Manager (TLS + routing, host-level, not part of this compose stack — see [docs/npm-proxy-hosts.md](docs/npm-proxy-hosts.md)).
- **Backend:** FastAPI (REST + WebSocket).
- **Workers:** Celery on Redis — one task per scrape batch, iterating its links sequentially; up to 10 batches run concurrently (`--concurrency=10`). See [PLAN.md §4.2](PLAN.md#42-the-worker-queue-the-core-design).
- **Database:** PostgreSQL via SQLAlchemy 2.0 (async) + Alembic. Models live in `shared/` — the single source of truth for both `api` and `worker`.
- **Proxy:** a self-hosted rotating gateway for Tier-2 scrape traffic only; official Tier-1 platform APIs always go direct. See [PLAN.md §4.8](PLAN.md#48-self-hosted-proxy-gateway-decided--no-commercial-providers).
- **Single host** at launch; no MinIO/S3 in v1 (local disk behind a `StorageBackend` interface).

## Repository layout

```
api/        FastAPI — scrapes/share/billing/admin/cms routes; fastapi-users auth; WS hub
worker/     Celery worker + beat (run_batch, watchdog, retention sweep, disk predictor, cascade)
proxy/      Self-hosted rotating proxy gateway (real: CONNECT/HTTP, SOCKS5 exits, sticky sessions)
web/        Next.js — input/dashboard/gallery, login/register/account, /admin/* (plain Tailwind)
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
([PLAN.md §4.5](PLAN.md#45-storage-retention--share-links)). That works
anonymously (public tier: 25 links/scrape, 10 scrapes per IP per 24h by
default).

Register at `/register` for a free account (50 links/scrape, 20 scrapes/day)
and a persistent history at `/account`, or upgrade to paid from there for
the full 100-link batch size and no daily cap. There's no email step in v1
(no mailer wired yet — see [PLAN.md §12](PLAN.md#12-open-decisions)), so
registering logs you straight in.

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

# auth (fastapi-users) — attach the bearer token to /api/scrapes and
# /api/me/scrapes to submit/list as that account instead of anonymously
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"..."}'
curl -X POST http://localhost:8000/api/auth/jwt/login \
  -H "Content-Type: application/x-www-form-urlencoded" -d "username=you@example.com&password=..."
# {"access_token": "...", "token_type": "bearer"}
curl http://localhost:8000/api/me/scrapes -H "Authorization: Bearer <access_token>"
```

Media lands on disk at `/data/scrapes/<scrape_id>/<category>/`, exactly
matching the ZIP layout the export endpoint streams directly from.

## Admin

Set `ADMIN_BOOTSTRAP_EMAIL` in `.env` before the first registration — that
email becomes admin (`is_superuser` + `role=ADMIN`) automatically, since
there's no panel yet to promote the first one. Then `/admin` has:

- **Overview** — live CPU/memory/disk and the disk-full forecast, plus proxy
  gateway health.
- **Settings** — override any `limits.<role>.<field>`, `retention_hours`, or
  `proxy_enabled` without a redeploy.
- **Credentials** — add a `PlatformCredential`; an *enabled* one is what
  actually switches that platform from the Tier-2 scrape fallback to the
  Tier-1 API path (§4.3) — no code change, no restart.
- **Legal pages** — edit Impressum/ToS/Privacy (or any slug), published at
  `/legal/<slug>`.
- **Audit log** / **Platform health** — who scraped what and when, and each
  platform's success rate + API-vs-fallback mix.
- **Residential nodes** ([§4.8a](PLAN.md#48a-residential-proxy-mesh--self-registering-agents--done)) —
  add a self-registering residential proxy node (e.g. a friend's home Docker
  box), get a one-time token, set priority. A connected, enabled node with
  the lowest priority number is preferred for Tier-2 scrape traffic; one
  that starts only erroring is automatically taken out of rotation for a
  cooldown period. See `docker-compose.agent.yml` for the deployment
  artifact that runs on the residential side — it makes an outbound-only
  connection, no port forwarding needed on that network.

Flower (`http://localhost:5555`) is behind HTTP basic auth —
`FLOWER_BASIC_AUTH=user:pass` in `.env` (change the example default before
any non-local deployment).

## License

Decided: **AGPLv3 + CLA** (dual-licensing) — genuinely open source while
closing the "SaaS loophole" that lets a competitor host an unmodified copy
for free without contributing back. `LICENSE`/`CLA.md` files are not yet
added to the repo; rationale in the meantime: [PLAN.md §11](PLAN.md#11-license-recommendation).
