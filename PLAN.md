# IngressFlow — Architecture & Delivery Plan

> Project & product name: **IngressFlow** (decided). The brief's working title "MediaFetch" is retired.
> Database/service identifiers below still read `ingressflow`.

A scalable, dockerized, open-source SaaS for public broadcasting stations to ingest (scrape) images and video from social-media links, sort them by editorial category, and export them as structured ZIPs — with a live dashboard, 6-hour retention, and tiered monetization.

**Confirmed decisions (from review):** name = IngressFlow · license = AGPLv3 + CLA · SSL termination = Nginx Proxy Manager (NPM) at the host edge · public tier = same gallery as paid, not account-bound, reached via a dynamic link, limited only by URLs & scrapes per IP per 24h.

---

## 1. Prompt Analysis — What We're Actually Building

Distilling the brief into hard requirements and the constraints that drive the architecture:

### Load & concurrency model (the defining constraint)
- **10 concurrent users**, each with an independent web session.
- Each user submits a **batch of up to 100 links**.
- Within a batch, links are processed **strictly sequentially** (a chain) to avoid IP blocks.
- Across users, batches run **concurrently**.
- → This is the single most important architectural driver. It is *not* "run 1000 scrapes in parallel." It is "≤10 sequential pipelines running side by side." This maps cleanly to **a fixed worker pool of ~10 slots, where each batch is one long-lived task that iterates over its links internally.** (Details in [§4.2](#42-the-worker-queue-the-core-design).)

### Functional surface
| Area | Requirement |
|---|---|
| Input | Paste textarea; category headers (`L1234`) group the URLs beneath them until a blank line / next header. |
| Platforms | TikTok, Instagram, YouTube, X.com, Reddit, Snapchat, Facebook, Vimeo. Highest quality. Dedup per link. **Official API first, scraping only as fallback** ([§4.3](#43-scraping-core--api-first-extractor-strategy)). |
| Config | Toggles: Video-only, Image-only, Include metadata JSON. |
| Lawful-use gate | Mandatory attestation checkbox per scrape ("I hold the rights/lawful basis") — **submit is rejected without it**; the acceptance is recorded and transfers responsibility to the operator ([§4.7](#47-audit--lawful-use-attestation)). |
| Audit | Append-only log of who started which scrape (actor/IP, URLs, config, attestation, extractor tier) — outlives the 6h media window ([§4.7](#47-audit--lawful-use-attestation)). |
| Anti-blocking | Randomized 1.8–4.2s delays, UA rotation, optional residential proxy (per-GB billed), optional admin OAuth/cookie injection. Applied on the **Tier-2 scrape-fallback path only**. |
| Live dashboard | WebSocket stats: progress `X/Y`, image/video counts, live total data size; per-URL status (green/yellow/red), per-URL `X/X images \| Y/Y videos`, copy-link button. Browser notification on batch completion. |
| Storage | 6-hour disk cache; per-scrape unauthenticated share link; hard-delete + link invalidation at exactly 6h. |
| Export | Single ZIP; folders named by category; gallery with ALL / by-category / by-link scopes, multi-select download, filtered-view ZIP, previews + native video. |
| Monetization | **Public tier** = the *same* gallery/export/library as paid, **not account-bound**, reached via a dynamically generated link; its *only* limits are URLs-per-scrape and scrapes-per-IP-per-24h. Registered free/paid tiers add accounts, higher limits, and persistent history (within 6h). Credit/subscription framework (Stripe-ready). |
| Admin | Live IO/CPU/disk; **disk-full predictor** (hourly, velocity + deletion-cycle aware); tunable limits; CMS for Impressum / ToS / Privacy. |

### Implicit requirements the brief doesn't state but we must handle
- **Legal/compliance is a first-class concern**, not an afterthought. "Impressum" ⇒ German/EU jurisdiction ⇒ GDPR. Scraping social platforms may violate their ToS and touches third-party copyright and personal data. See [§10](#10-legal--compliance-risk).
- **Cancellation**: a user must be able to abort a running 100-link batch (5 min+ of runtime). The task model must support cooperative cancellation.
- **Crash resilience**: a worker dying mid-batch must not lose the 60 links already done. ⇒ per-link checkpointing to Postgres.
- **Back-pressure**: when all 10 slots are busy, the 11th user's batch must queue with a visible "position in queue," not fail.

---

## 2. Stack Review — Proposed vs. Recommended

The proposed stack is sound. My changes are additive and low-risk; each is justified.

| Layer | Brief | Recommendation | Rationale |
|---|---|---|---|
| Frontend | Next.js + Tailwind + shadcn/ui + WS | **Keep.** Next.js App Router, TanStack Query for server state, `zustand` for local UI state. | Nothing to improve. shadcn/ui is ideal for a dense dashboard. |
| Backend | FastAPI | **Keep.** Add **Pydantic v2** schemas, **Alembic** migrations. | FastAPI's async model suits the WS + I/O-bound scraping orchestration. |
| Queue | Celery **or** RQ + Redis | **Celery** (decided). | Celery's `revoke`, per-task time limits, custom routing, and mature monitoring (Flower) matter for cancellable long-running batches. RQ is simpler but weaker on cancellation/observability. |
| Task shape | (unspecified) | **One task per batch, iterating internally** — *not* a 100-task chain. | Keeps browser/proxy/cookie session affinity for the whole batch, makes pacing/human-mimicry trivial, simplifies cancellation and progress. See [§4.2](#42-the-worker-queue-the-core-design). |
| Media acquisition | yt-dlp + Playwright | **API-first, scrape-fallback.** Official platform APIs (Tier 1) → yt-dlp / **gallery-dl** / Playwright (Tier 2). | The lawful path ([§10](#10-legal--compliance-risk)) requires trying ToS-compliant official APIs first; scraping (with residential proxy / OAuth-cookie auth) is the fallback only where no API is usable. `gallery-dl` added for image galleries. Full tiering in [§4.3](#43-scraping-core--api-first-extractor-strategy). |
| DB | PostgreSQL + SQLAlchemy | **Keep.** SQLAlchemy 2.0 async + Alembic. | — |
| Cache/broker | Redis | **Keep — and use it for 3 jobs**: Celery broker/result backend, **Pub/Sub for WebSocket fan-out**, and rate-limit counters. | Pub/Sub decouples workers from the web layer (workers publish progress; the FastAPI WS process subscribes and forwards). Critical for the realtime design. |
| Object storage | local disk | **Local volume now, behind a storage interface** so **MinIO/S3** can swap in later. | 6h retention + ZIP assembly + disk-full predictor all assume local disk today; the interface avoids a rewrite when scaling past one host. |
| Edge / TLS | (none) | **Nginx Proxy Manager (NPM)** at the host edge (decided). | NPM terminates TLS and routes `/`, `/api`, `/ws` (with WebSocket upgrade) to the `web` and `api` containers — GUI-managed certs. It sits *in front of* the compose stack, so it is not a stack service. **Traefik is optional internally** if we later want container-native service discovery; not required for v1. |
| Auth | (implied) | **fastapi-users** (JWT + refresh) or Authlib. | Batteries-included registration, verification, password reset — don't hand-roll. |
| Billing | Stripe-ready | **Stripe** (Checkout + Billing + webhooks). | Framework only in early phases; wire real products later. |
| Observability | (none) | **Flower** (Celery), **structured JSON logs**, optional Prometheus/Grafana later. | The admin dashboard needs real metrics; don't invent them ad hoc. |

**Net new services vs. the brief:** Flower (Celery ops) inside the stack, and Nginx Proxy Manager at the host edge (outside the stack). Everything else is a library choice inside existing containers.

---

## 3. System Architecture (Component View)

```
                       (host edge, in front of the stack)
                              ┌──────────────────────────────┐
                              │   Nginx Proxy Manager (NPM)  │  TLS termination, routing, WS upgrade
                              └───────┬───────────────┬──────┘
                                      │               │
                     https/ wss      │               │  /api  /ws
                                      ▼               ▼
                        ┌──────────────────┐   ┌────────────────────────┐
                        │  Next.js (web)   │   │   FastAPI (api + ws)    │
                        │  dashboard, UI   │   │  REST + WebSocket hub   │
                        └──────────────────┘   └───────┬────────────────┘
                                                        │
              enqueue batch │            publish/subscribe │        read/write
                            ▼                              ▼                   ▼
                 ┌────────────────────┐        ┌──────────────────┐   ┌─────────────────┐
                 │       Redis        │◀──────▶│  Redis Pub/Sub   │   │   PostgreSQL    │
                 │ broker + results   │        │ (progress events)│   │ users, scrapes, │
                 │ + rate counters    │        └────────▲─────────┘   │ items, media,   │
                 └─────────┬──────────┘                 │             │ cms, settings   │
                           │ dispatch                   │ publish     └────────▲────────┘
                           ▼                            │                      │
                 ┌──────────────────────────────────────┴──────────────────────┴───────┐
                 │                 Celery Workers  (concurrency = 10)                    │
                 │  each slot runs ONE batch task → sequential link loop                 │
                 │  [ delay(1.8–4.2s) → yt-dlp / gallery-dl / Playwright → checkpoint ]  │
                 └───────────────────────────────┬───────────────────────────────────────┘
                                                 │ writes media
                                                 ▼
                                    ┌────────────────────────────┐
                                    │  Storage volume (local)     │  behind StorageBackend iface
                                    │  /data/scrapes/<scrape_id>/ │  (S3/MinIO-swappable)
                                    └────────────────────────────┘

        ┌───────────────────────────────────────────────────────────────────┐
        │  Celery Beat (scheduler):                                           │
        │   • retention sweep (every 1 min): hard-delete scrapes > 6h,        │
        │     invalidate share links                                          │
        │   • disk-full predictor (hourly): recompute fill-time forecast      │
        └───────────────────────────────────────────────────────────────────┘
```

### 3.1 Container inventory (Docker Compose services)
`web` (Next.js) · `api` (FastAPI: REST + WS) · `worker` (Celery, `--concurrency=10`) · `beat` (Celery Beat) · `redis` · `postgres` · `flower` (admin/ops) · (later: `minio`).

**TLS/edge is handled by Nginx Proxy Manager running in front of the host**, outside this stack (its own container/host). The compose stack exposes `web` and `api` to NPM; NPM owns certificates and public routing.

---

## 4. Core Architectural Blueprints

### 4.1 Batch lifecycle (state machine)

```
Scrape:  QUEUED ─▶ RUNNING ─▶ COMPLETED ─▶ EXPIRED (6h)
             │         │  \
             │         │   └─▶ PARTIAL   (finished, some items failed)
             │         └────▶ CANCELLED  (user abort)
             └──────────────▶ FAILED     (fatal / worker crash unrecovered)

ScrapeItem (one URL):  PENDING ─▶ SCRAPING ─▶ SUCCESS
                                          ├─▶ PARTIAL  (some media failed)
                                          └─▶ FAILED
```

### 4.2 The worker queue — the core design

**Requirement:** sequential within a batch, concurrent across batches, ≤10 simultaneous.

**Decision: one Celery task per batch, iterating links internally**, with worker `concurrency=10`. We deliberately reject the "chain of 100 subtasks" pattern.

Why one task per batch beats a 100-task chain:
- **Session affinity** — one worker holds the same Playwright browser context, cookie jar, and proxy IP for the whole batch. A chain scatters links across workers/IPs, defeating the anti-block goal.
- **Human mimicry pacing** is a simple `sleep(random.uniform(1.8, 4.2))` inside the loop — no cross-task scheduling gymnastics.
- **Cancellation** is one `revoke(terminate)` + a cooperative `is_cancelled` check between links.
- **Concurrency cap** is just `--concurrency=10`. The 11th batch waits in Redis; its queue position is derivable and shown to the user.

Crash resilience (the trade-off we pay for): a chain gets free per-link retry granularity; a single task doesn't. We recover it explicitly:
- Every link result is **checkpointed to Postgres immediately** (`ScrapeItem` row updated as each URL finishes).
- The batch task is **idempotent + resumable**: on retry it skips items already in a terminal state, so a crashed batch resumes from the last checkpoint rather than restarting.
- `acks_late=True` + `task_reject_on_worker_lost=True` so an in-flight batch is redelivered if its worker dies.

Sketch:

```python
@celery.task(bind=True, acks_late=True, task_reject_on_worker_lost=True)
def run_batch(self, scrape_id: str):
    scrape = load_scrape(scrape_id)
    mark_running(scrape)
    session = build_session(scrape)          # UA, proxy IP, cookies — held for whole batch

    for item in pending_items(scrape):       # resumable: only PENDING/SCRAPING
        if is_cancelled(scrape_id):          # cooperative cancel (Redis flag)
            mark_cancelled(scrape); break
        jitter_sleep(1.8, 4.2)               # human mimicry
        result = extract(item.url, session, scrape.config)   # yt-dlp/gallery-dl/Playwright
        persist_item_result(item, result)    # checkpoint to Postgres + write media to disk
        publish_progress(scrape_id, snapshot(scrape))        # Redis Pub/Sub → WS

    finalize(scrape)                          # COMPLETED / PARTIAL, compute totals
    publish_done(scrape_id)                   # triggers browser notification
```

**Queue routing:** a single `scrapes` queue is sufficient — the `concurrency=10` cap *is* the "10 users" limit. (If per-tenant fairness becomes an issue, upgrade to per-user rate limits or a fair-scheduling broker later; not needed for v1.)

### 4.3 Scraping core — **API-first extractor strategy**

The lawful path ([§10](#10-legal--compliance-risk)) drives the extractor order: **official APIs first, scraping only as fallback where no usable API exists.** Per URL we resolve the platform, then walk tiers top-down; **first success wins**; dedup by resolved media URL/content hash.

**Tier 1 — Official platform API (preferred, ToS-compliant).** The only route that doesn't breach platform terms. Attempted first whenever credentials are configured and the API can serve the asset:
- **YouTube Data API**, **Vimeo API**, **Meta Graph API** (Instagram/Facebook), **TikTok Research/Display API**, **X API**, **Reddit API**.
- APIs are rate-limited and coverage is partial (some content/media isn't retrievable, some platforms — e.g. Snapchat — have no suitable public API). Missing/failed API access falls through to Tier 2.
- API credentials are admin-configured per platform and stored encrypted (same handling as cookies, [§10](#10-legal--compliance-risk)).

**Tier 2 — Fallback scraping (used only when no API is provided/usable for that platform).** This is where legal risk concentrates and where **residential proxy + OAuth/cookie auth** apply:
- **yt-dlp** — video (YouTube, TikTok, Vimeo, X, Facebook, Reddit video); highest-quality format (`bestvideo+bestaudio/best`).
- **gallery-dl** — image sets/carousels (Instagram, Reddit galleries, X media, Snapchat spotlight).
- **Playwright** — JS-walled / login-gated content; also the vehicle for **admin OAuth/cookie injection** (Instagram/X session) and dynamically-rendered media.
- Residential proxy and cookie/OAuth auth are **admin-gated, off by default**, and only ever engaged on the Tier-2 path.

Each extractor records **which tier/method served the item** (`MediaFile.source_method` = `api` \| `ytdlp` \| `gallerydl` \| `playwright`) so the audit log ([§4.7](#47-audit--lawful-use-attestation)) and per-platform health view can show the API-vs-scrape mix and where fallback is being hit.

Config toggles (`video_only`, `image_only`, `include_metadata`) filter what each tier keeps. Metadata JSON is written alongside media when enabled.

### 4.4 Realtime pipeline (WebSockets)

Workers **must not** hold WebSocket connections. Flow:
1. Worker publishes a progress snapshot to Redis Pub/Sub channel `scrape:{id}`.
2. FastAPI WS process subscribes to that channel and forwards to the browser(s) watching that scrape.
3. On `done`, the frontend fires the **Web Notification API** alert.

This keeps workers stateless w.r.t. connections and lets multiple browser tabs / a reconnecting client all receive updates. WS auth via short-lived token; the unauthenticated **share-link** grants read-only WS + gallery access scoped to one scrape.

### 4.5 Storage, retention & share links
- Layout: `/data/scrapes/{scrape_id}/{category}/{filename}` — mirrors the ZIP structure, so export is a straight `zipstream` walk (no repacking, low memory).
- Share link: `share_token` (unguessable) on the `Scrape` row; unauthenticated read access to gallery + ZIP until expiry.
- **Retention sweep** (Celery Beat, every 60s for tight tolerance on "exactly 6h"): find scrapes past `expires_at`, hard-delete the directory, null the media, invalidate `share_token`, mark `EXPIRED`.
- `expires_at = created_at + retention_hours` (retention configurable by admin).

### 4.6 Disk-full predictor (admin)
Hourly Beat task. Model net disk velocity accounting for the 6h deletion cycle:
- Sample `bytes_in_per_hour` (rolling avg of recent scrape output) and `bytes_out_per_hour` (data aging past 6h and being deleted).
- `net_rate = bytes_in − bytes_out`. If `net_rate ≤ 0`: **stable, no forecast**. If `> 0`: `hours_to_full = free_bytes / net_rate`, surfaced with a confidence band and a threshold alert (e.g. warn at <24h).
- Store hourly samples in a `disk_samples` table so the admin chart shows the trend, not just a number.

### 4.7 Audit & lawful-use attestation

The operator — not the tool — carries the rights ([§10](#10-legal--compliance-risk)). Two mechanisms make that concrete and defensible:

**Lawful-use attestation (gate before scrape).** Every scrape submission requires a checked **"I confirm I have the rights/lawful basis to ingest this content for editorial use"** box. The submit endpoint **rejects the batch if it is not checked** — the attestation is not decorative. We persist the exact attestation text/version, who accepted it, when, and from which IP, bound to the scrape. This is what transfers responsibility to the operator.

**Audit log (who scraped what, when).** An append-only `AuditLog` records every scrape start (and other sensitive actions: credential/cookie changes, proxy toggles, share-link access, takedowns). For each scrape start we store: actor (user id or anonymous+IP), timestamp, the submitted URLs/categories, config, the attestation record id, and the extractor tiers used. Append-only (no update/delete via app), retained beyond the 6h media window for accountability, exportable for a takedown/DSAR response.

Together these answer "who started which scrape, under what asserted rights" — the two questions a broadcaster's legal team and any complainant will ask.

---

## 5. Data Model (core entities)

```
User            id, email, hashed_pw, role[public|free|paid|admin], stripe_customer_id,
                credit_balance, created_at
Scrape          id, user_id (nullable for public), status, config(jsonb: video_only/…),
                share_token, total_images, total_videos, total_bytes,
                created_at, expires_at, proxy_used, ua_used, attestation_id
Category        id, scrape_id, name (e.g. "L1234"), order
ScrapeItem      id, scrape_id, category_id, url, platform, status, images_found, images_ok,
                videos_found, videos_ok, error, started_at, finished_at
MediaFile       id, item_id, category_id, type[image|video], path, bytes, width, height,
                duration, source_url, source_method[api|ytdlp|gallerydl|playwright],
                checksum (dedup), metadata_json
UsageEvent      id, user_id, ip, scrape_id, links_count, bytes, proxy_gb, created_at   (billing/limits)
Setting         key, value        (max_links, max_scrapes_per_ip_24h, retention_hours, proxy_enabled…)
CmsPage         slug[impressum|tos|privacy], content_md, updated_at, updated_by
PlatformCredential  platform, kind[api_key|oauth_token|cookie], secret_blob(encrypted),
                added_by, valid_until, enabled          # Tier-1 API keys AND Tier-2 cookies/OAuth
LawfulAttestation   id, scrape_id, text_version, accepted (bool), actor_user_id (nullable),
                actor_ip, accepted_at                    # the transferred-rights record (§4.7)
AuditLog        id, ts, actor_user_id (nullable), actor_ip, action, target_type, target_id,
                detail(jsonb)                             # append-only; who did what, when (§4.7)
DiskSample      id, ts, free_bytes, bytes_in_rate, bytes_out_rate, hours_to_full
```

Notes:
- `PlatformCredential.secret_blob` (Tier-1 API keys, Tier-2 OAuth tokens/cookies) is **encrypted at rest** ([§10](#10-legal--compliance-risk)); never exposed to non-admin users or in API responses. This replaces the earlier `AdminCookie` table and covers both API and scrape-fallback credentials.
- `LawfulAttestation` is required for every `Scrape`; a batch with `accepted = false`/absent is rejected at submit ([§4.7](#47-audit--lawful-use-attestation)).
- `AuditLog` is **append-only** (no app-level update/delete) and outlives the 6h media window.

---

## 6. Proposed Directory Structure

```
IngressFlow/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── PLAN.md
├── LICENSE                      # AGPL-3.0 (see §11)
├── CLA.md                       # contributor license agreement (enables dual-licensing)
├── docs/npm-proxy-hosts.md      # NPM edge config reference (TLS + routing, host-level)
├── web/                         # Next.js
│   ├── Dockerfile
│   ├── app/                     # App Router: /, /scrape, /gallery/[token], /admin, /pricing, /(legal)
│   ├── components/ui/           # shadcn/ui
│   ├── components/dashboard/    # live stats, url list, gallery
│   ├── lib/ws.ts                # WebSocket client + reconnect
│   └── lib/api.ts               # TanStack Query hooks
├── api/                         # FastAPI
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes/          # scrapes, auth, gallery, admin, billing, cms, share, audit, takedown
│   │   ├── ws/                  # connection hub + Redis Pub/Sub subscriber
│   │   ├── models/              # SQLAlchemy
│   │   ├── schemas/             # Pydantic v2
│   │   ├── services/            # parsing, limits, storage iface, billing, audit, attestation
│   │   ├── core/                # config, security, deps
│   │   └── db/                  # session, alembic env
│   └── alembic/
├── worker/                      # Celery (shares api models via installed package or shared dir)
│   ├── Dockerfile
│   ├── celery_app.py
│   ├── tasks/
│   │   ├── batch.py             # run_batch (§4.2)
│   │   ├── retention.py         # 6h sweep (§4.5)
│   │   └── predictor.py         # disk forecast (§4.6)
│   └── scraping/
│       ├── extractors/          # api/ (per-platform Tier-1), ytdlp.py, gallerydl.py, playwright.py
│       ├── resolver.py          # url → platform; picks Tier-1 API vs Tier-2 fallback
│       ├── session.py           # UA rotation, proxy, cookie injection
│       └── parser.py            # category-header text parsing
├── shared/                      # models/schemas shared by api + worker (single source of truth)
└── docs/
    ├── ARCHITECTURE.md
    ├── DEPLOYMENT.md
    └── COMPLIANCE.md            # GDPR / ToS / takedown process
```

---

## 7. Docker Compose Blueprint (v1, dev)

TLS and public routing live in **Nginx Proxy Manager on the host, in front of this stack** — so no proxy service appears here. NPM forwards to `web:3000` and `api:8000` (proxy-host config kept in `docs/npm-proxy-hosts.md`).

```yaml
services:
  web:
    build: ./web
    expose: ["3000"]              # reached by NPM on the host network / shared docker net
    depends_on: [api]

  api:
    build: ./api
    expose: ["8000"]             # NPM routes /api and /ws here (WS upgrade enabled in NPM)
    environment:
      - DATABASE_URL=postgresql+asyncpg://ingressflow:ingressflow@postgres:5432/ingressflow
      - REDIS_URL=redis://redis:6379/0
    depends_on: [postgres, redis]

  worker:
    build: ./worker
    command: celery -A celery_app worker --concurrency=10 -Q scrapes --loglevel=info
    environment: [same DB/REDIS as api]
    volumes: ["media:/data/scrapes"]
    depends_on: [redis, postgres]
    # Playwright browsers baked into the image; consider shm_size: 1gb

  beat:
    build: ./worker
    command: celery -A celery_app beat --loglevel=info
    depends_on: [redis, postgres]

  flower:
    build: ./worker
    command: celery -A celery_app flower --port=5555
    expose: ["5555"]             # exposed only via an NPM proxy host behind admin auth in prod

  redis:
    image: redis:7-alpine
    volumes: ["redis:/data"]

  postgres:
    image: postgres:16-alpine
    environment: [POSTGRES_USER=ingressflow, POSTGRES_PASSWORD=ingressflow, POSTGRES_DB=ingressflow]
    volumes: ["pgdata:/var/lib/postgresql/data"]

volumes: { media: {}, redis: {}, pgdata: {} }
```

> **Reaching the stack from NPM:** put NPM and this stack on a shared Docker network (or expose `web`/`api` on host ports NPM forwards to). Keep raw ports off the public interface — NPM is the only public entrypoint.

Prod overlay (`docker-compose.prod.yml`): secrets, resource limits, `worker` replicas or higher concurrency behind the 10-slot policy, MinIO if introduced, log shipping. (TLS/certs are NPM's job, not the overlay's.)

> **Note on the media volume:** `worker` writes media; `api` serves gallery/ZIP. In v1 both mount the shared `media` volume (single host). When scaling to multiple hosts, this is exactly the seam where the `StorageBackend` interface swaps local disk for MinIO/S3.

---

## 8. Feature Improvements Over the Brief

Suggestions the brief invited — take or leave per phase:
1. **Queue position + ETA** on the dashboard when all 10 slots are busy (the brief implies 10 concurrent but says nothing about the 11th user). Cheap given the queue model.
2. **Resume/retry failed items** — re-run only the red/yellow URLs of a finished scrape without re-scraping the successes. Falls out naturally from per-item checkpointing.
3. **`gallery-dl` addition** (see [§2](#2-stack-review--proposed-vs-recommended)) — materially better image coverage than Playwright-only.
4. **Duplicate detection by checksum**, not just by source URL — the brief says "avoid duplicates per link"; content-hash dedup also catches the same asset reposted across links within a batch.
5. **API-first acquisition + lawful-use attestation + audit log** — now core, not optional (see [§4.3](#43-scraping-core--api-first-extractor-strategy) and [§4.7](#47-audit--lawful-use-attestation)). Plus a **takedown/DMCA endpoint** that writes to the same audit trail.
6. **Per-platform health indicator** in admin — extractors break when platforms change; surface success rates *and the API-vs-fallback ratio* per platform so ops sees breakage (and silent fallback to the riskier scrape path) early.
7. **Storage interface from day one** — trivial now, saves a painful migration later.

---

## 9. Phased Delivery Plan

Each phase ends with something demonstrable. Rough sizing assumes a small team; treat as sequencing, not a calendar commitment.

### Phase 0 — Foundations
- Repo scaffold, Docker Compose (all services boot), NPM edge proxy hosts documented + WS upgrade verified, `.env.example`.
- Postgres + Alembic baseline migration; SQLAlchemy models from [§5](#5-data-model-core-entities); Redis wired to Celery.
- Health checks + a "hello" round trip: web → api → db → redis.
- **Exit:** `docker compose up` yields a reachable frontend and a green `/api/health`.

### Phase 1 — Acquisition engine (headless, no UI polish)
- Category-header **text parser** (`L1234` grouping); URL → platform **resolver**.
- `run_batch` task ([§4.2](#42-the-worker-queue-the-core-design)): sequential loop, jitter delays, UA rotation, per-item checkpointing, cancellation, resume-on-crash.
- **API-first tiering** ([§4.3](#43-scraping-core--api-first-extractor-strategy)): Tier-1 official APIs where credentials exist → Tier-2 yt-dlp / gallery-dl / Playwright fallback; record `source_method` per item; config toggles; media written to `/data/scrapes/...`.
- **Attestation gate + audit log** ([§4.7](#47-audit--lawful-use-attestation)): submit rejected without accepted attestation; every scrape start written to append-only `AuditLog`. (Build the enforcement here, at the API boundary, so no path can bypass it.)
- **Exit:** a batch with a valid attestation runs (API-first, scrape-fallback) across 10 concurrent slots; a batch *without* attestation is rejected; audit rows recorded; media on disk in ZIP-ready layout.

### Phase 2 — Realtime dashboard
- Redis Pub/Sub → FastAPI WS hub → browser ([§4.4](#44-realtime-pipeline-websockets)).
- Input UI (textarea + toggles + **mandatory lawful-use checkbox** wired to the Phase-1 gate), top-bar stats, per-URL list with status icons + copy-link, queue position.
- Web Notification API on completion.
- **Exit:** paste links, accept attestation, watch live progress + completion notification end to end; submit is blocked if the checkbox is unchecked.

### Phase 3 — Storage, retention, export, gallery
- `StorageBackend` interface (local impl); streamed ZIP export (category folders).
- Retention sweep (6h hard-delete + share-link invalidation); share-link read access.
- Gallery: ALL / category / single-link scopes, multi-select download, filtered-view ZIP, image previews + native video.
- **Exit:** share link works unauthenticated; ZIP structure correct; data provably gone at 6h.

### Phase 4 — Users, tiers & monetization
- `fastapi-users` auth (register/verify/reset); roles.
- **Public tier**: no account; each scrape yields a dynamic share link to the *full* gallery/export (same library as paid). Gated **only** by max-URLs-per-scrape and max-scrapes-per-IP-per-24h (Redis counters keyed by IP). Registered free/paid tiers add persistent history + higher limits.
- Stripe scaffolding (Checkout, webhooks, credit/subscription framework) — products can stay in test mode.
- **Exit:** an anonymous visitor scrapes within IP limits and gets a working share-linked gallery; a registered/paid account raises the limits and keeps history.

### Phase 5 — Admin dashboard
- Live IO/CPU/disk (host metrics); Flower behind admin auth.
- **Disk-full predictor** ([§4.6](#46-disk-full-predictor-admin)) with trend chart.
- Settings (limits, retention); CMS for Impressum/ToS/Privacy; **encrypted `PlatformCredential` UI** for Tier-1 API keys *and* Tier-2 OAuth/cookies; proxy toggle + per-GB usage accounting.
- **Audit log viewer** (search/export who-scraped-what) and **per-platform health** incl. the API-vs-fallback mix (`source_method`).
- **Exit:** admin can tune limits, edit legal pages, add API keys/cookies, read the disk forecast, and query the audit log.

### Phase 6 — Hardening & launch
- Compliance pass ([§10](#10-legal--compliance-risk)): DMCA/takedown endpoint (writes to audit log), attestation-text/ToS legal sign-off, GDPR data-handling doc, secret-encryption review.
- Load test the 10-slot model; failure injection (kill a worker mid-batch → verify resume).
- Prod overlay, TLS, backups, monitoring/alerting, structured logs.
- **Exit:** production deploy runbook; passes a security + compliance review.

---

## 10. Legal & Compliance (Risk)

This must be designed in, not bolted on — the target users are **public broadcasters in an Impressum (EU/German) jurisdiction**.

### Is there a lawful way to operate this? (Yes, with conditions)
*Not legal advice — get German media-law counsel before launch.* A defensible path exists and should shape the product:

1. **API-first, scraping as fallback.** Use official platform APIs where they exist (YouTube Data, Meta Graph, TikTok, Vimeo) — the only route that doesn't breach platform ToS. Scraping is the fallback and is where risk concentrates.
2. **The operator holds the rights, not the tool.** The lawful use case is a broadcaster ingesting content they have a licence to, or that fits a statutory exception, for editorial review. The software *enables* this; it can't *enforce* it. This is made concrete by the **mandatory per-scrape lawful-use attestation + append-only audit log** ([§4.7](#47-audit--lawful-use-attestation)): the operator must actively assert rights to submit, and every scrape is attributable.
3. **Lean on the press privilege.** DE/EU exceptions — §50 UrhG (current-events reporting), §51 (quotation), and crucially the **Medienprivileg / GDPR Art. 85 journalism exemption** — are exactly why this fits *public broadcasters* far better than a general-audience tool. The 6h auto-delete reinforces the "transient editorial ingest, not an archive" position (data minimisation).
4. **Two legal layers, kept separate:** *copyright/GDPR* (addressed by exceptions + rights ownership) vs. *platform ToS* (contract law — breach is generally civil, not criminal, but still real). Login-wall **cookie bypass** and **residential proxies** raise exposure materially: keep them **admin-only, off by default, and a documented sign-off**, never a user-facing default.

**Bottom line:** lawful is achievable if you (a) prefer official APIs, (b) restrict use to rights-holding editorial staff under the press privilege, (c) keep 6h auto-delete + audit log + takedown, and (d) put lawful-use responsibility on the operator in the ToS.


- **Platform ToS**: automated scraping of TikTok/Instagram/X/etc. generally violates their terms. Cookie injection to bypass login walls increases exposure. This is a product/legal risk the operator must accept and document; the software should make lawful use *possible* (e.g. only content the org has rights to) but cannot enforce it.
- **Copyright**: scraped media is third-party IP. The 6h retention window helps ("transient ingest for editorial review") but does not confer rights. The **mandatory lawful-use attestation** ([§4.7](#47-audit--lawful-use-attestation)) puts the rights assertion on the operator per scrape; the **append-only audit log** + **takedown endpoint** answer "who scraped what, when, from where, under what asserted basis."
- **GDPR**: scraped media often contains personal data. Document lawful basis, retention (the 6h auto-delete is a strong data-minimization story), and data-subject request handling. Ship a `COMPLIANCE.md`.
- **Secrets at rest**: admin cookies and proxy API keys are high-value credentials — **encrypt at rest** (e.g. Fernet/KMS), never log them, never return them in API responses, scope to admin only.
- **Abuse**: rate limits + per-IP caps + the public-tier link cap mitigate the tool being used as a bulk scraper. Keep the audit log.

Recommend a short legal review before Phase 6 and a clear ToS that pushes lawful-use responsibility onto the operator.

---

## 11. License Recommendation

**Goal (from you):** open source, but able to monetize as SaaS without a cloud provider or competitor taking the code and running a rival hosted service for free.

The core tension: **permissive licenses (MIT/Apache) don't protect SaaS** — anyone can host your code as a competing service and owe you nothing. Plain **GPL doesn't help either**, because running software as a network service isn't "distribution," so the GPL's share-back obligation never triggers (the "SaaS loophole").

### Recommended: AGPLv3 + Contributor License Agreement (dual-licensing)

- **AGPLv3** closes the SaaS loophole: anyone who runs a *modified* version as a network service **must publish their source**. It is **OSI-approved, genuinely open source**, so the "Open Source" promise is real. Competitors can still host it — but only if they open-source their changes, which strongly deters commercial free-riding.
- **+ a CLA** (contributors assign/license their contributions to you) lets you **dual-license**: the public gets AGPLv3; companies that want to embed/host it *without* AGPL obligations buy a **commercial license from you**. This is the exact model used by GitLab, Grafana(historically), Mattermost, and MongoDB(pre-SSPL). It is how you monetize while staying open source.

**Your own SaaS is unaffected** — you own the code, so AGPL obligations don't constrain you; they constrain everyone else.

### Alternatives, if strict OSI "open source" is *not* a hard requirement

If you want stronger anti-competition protection and can accept **"source-available"** (publicly readable, but not OSI-open):

| License | What it does | Trade-off |
|---|---|---|
| **FSL-1.1** (Functional Source License, by Sentry) | Blocks *competing* commercial use for **2 years**, then auto-converts to **Apache-2.0/MIT**. | Not OSI-open during the 2y window; simplest anti-compete story. |
| **BUSL-1.1** (Business Source License, MariaDB/HashiCorp) | You define a usage grant; restricted uses need a commercial license; converts to a permissive license after ≤4 years. | Not OSI-open until conversion; most flexible, slightly more legal overhead. |
| **Elastic v2 / SSPL** | Forbids offering the software as a managed service. | SSPL is controversial and *not* OSI-approved; heavier. |

### Recommendation
**Start with AGPLv3 + a CLA.** It is the only option that is *both* truly open source *and* SaaS-protective, and the CLA keeps the door open to commercial dual-licensing revenue. If, after launch, you find you need to explicitly bar hosted competitors, **relicensing new versions to FSL-1.1 or BUSL-1.1 is straightforward because the CLA already gave you the rights to do so.** Adopt the CLA from commit one — retrofitting it after external contributions is painful.

> Action items: add `LICENSE` (AGPL-3.0), add `CLA.md`, add SPDX headers, and state the dual-licensing offer in the README.

---

## 12. Open Decisions

**Resolved in review:**
- ✅ **Name** = IngressFlow (MediaFetch retired).
- ✅ **License** = AGPLv3 + CLA.
- ✅ **Edge/TLS** = Nginx Proxy Manager at the host; Traefik optional internal only.
- ✅ **Public tier** = full gallery/export, not account-bound, via dynamic link; limited only by URLs/scrape and scrapes/IP/24h.

**Still open:**
1. **Strict "exactly 6h"**: the 60s sweep gives ≤60s tolerance. If truly exact, additionally gate access by `now() > expires_at` at read time (defense in depth) — recommend doing both.
2. **Proxy providers**: Bright Data vs. Oxylabs — pick one to integrate first (interface stays generic).
3. **Single-host vs. multi-host** at launch — determines whether MinIO lands in Phase 3 or later. Default: single-host + storage interface, MinIO deferred.
4. **API-first coverage**: API-first is now decided ([§4.3](#43-scraping-core--api-first-extractor-strategy)); still open is *which* platforms get a Tier-1 API integration in v1 vs. ship scrape-only initially (each API = credentials + quota + a per-platform client). Suggested v1 Tier-1: YouTube, Vimeo (well-documented, media-retrievable); Meta/TikTok/X/Reddit APIs staged as credentials/approval land; Snapchat scrape-only (no suitable API).
5. **Attestation wording**: the exact legal text of the lawful-use checkbox needs counsel sign-off (versioned in `LawfulAttestation.text_version`).
```
