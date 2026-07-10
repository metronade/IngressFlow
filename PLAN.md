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
| Anti-blocking | Randomized 1.8–4.2s delays, UA rotation, optional **self-hosted rotating proxy gateway** (own Docker service, no commercial provider — [§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)), optional admin OAuth/cookie injection. Applied on the **Tier-2 scrape-fallback path only**. |
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
| Media acquisition | yt-dlp + Playwright | **API-first, scrape-fallback.** Official platform APIs (Tier 1) → yt-dlp / **gallery-dl** / Playwright (Tier 2). | The lawful path ([§10](#10-legal--compliance-risk)) requires trying ToS-compliant official APIs first; scraping (via the self-hosted proxy gateway + OAuth-cookie auth) is the fallback only where no API is usable. `gallery-dl` added for image galleries. **v1 ships scrape-only** (APIs built but inactive). Full tiering in [§4.3](#43-scraping-core--api-first-extractor-strategy). |
| DB | PostgreSQL + SQLAlchemy | **Keep.** SQLAlchemy 2.0 async + Alembic. | — |
| Cache/broker | Redis | **Keep — and use it for 3 jobs**: Celery broker/result backend, **Pub/Sub for WebSocket fan-out**, and rate-limit counters. | Pub/Sub decouples workers from the web layer (workers publish progress; the FastAPI WS process subscribes and forwards). Critical for the realtime design. |
| Object storage | local disk | **Single-host local volume** (decided), behind a `StorageBackend` interface. | Launch is **single-host** ([§12](#12-open-decisions)); 6h retention + ZIP assembly + disk-full predictor all assume local disk. The interface keeps MinIO/S3 as a *future* swap but **MinIO is not built in v1**. |
| Proxy / anti-block | commercial residential (Bright Data/Oxylabs) | **Own Docker rotating proxy gateway** (decided), behind a generic `ProxyBackend` interface. | Self-hosted, no per-GB provider billing; per-batch exit-IP affinity + rotation. Residential quality depends on attached upstream exits — see the caveat in [§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers). |
| Edge / TLS | (none) | **Nginx Proxy Manager (NPM)** at the host edge (decided). | NPM terminates TLS and routes `/`, `/api`, `/ws` (with WebSocket upgrade) to the `web` and `api` containers — GUI-managed certs. It sits *in front of* the compose stack, so it is not a stack service. **Traefik is optional internally** if we later want container-native service discovery; not required for v1. |
| Auth | (implied) | **fastapi-users** (JWT + refresh) or Authlib. | Batteries-included registration, verification, password reset — don't hand-roll. |
| Billing | Stripe-ready | **Stripe** (Checkout + Billing + webhooks). | Framework only in early phases; wire real products later. |
| Observability | (none) | **Flower** (Celery), **structured JSON logs**, optional Prometheus/Grafana later. | The admin dashboard needs real metrics; don't invent them ad hoc. |

**Net new services vs. the brief:** Flower (Celery ops) and the self-hosted `proxy` gateway ([§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)) inside the stack, and Nginx Proxy Manager at the host edge (outside the stack). Everything else is a library choice inside existing containers.

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
                 │  Tier-1 API (direct) ──or── Tier-2 [delay → yt-dlp/gallery-dl/        │
                 │  Playwright → checkpoint]                                             │
                 └───────┬───────────────────────────────────────────────┬──────────────┘
                writes   │ media                          Tier-2 outbound │ (scrape only)
                         ▼                                                ▼
            ┌────────────────────────────┐              ┌────────────────────────────────┐
            │  Storage volume (local)     │              │  proxy  (self-hosted gateway)  │
            │  /data/scrapes/<scrape_id>/ │              │  rotating exit IPs, 1 IP/batch │
            │  behind StorageBackend iface│              │  behind ProxyBackend iface     │
            └────────────────────────────┘              └───────────────┬────────────────┘
                                                             upstream exits (operator-fed) │
                                                                                           ▼
                                                                                     internet

        ┌───────────────────────────────────────────────────────────────────┐
        │  Celery Beat (scheduler):                                           │
        │   • retention sweep (every 1 min): hard-delete scrapes > 6h,        │
        │     invalidate share links                                          │
        │   • disk-full predictor (hourly): recompute fill-time forecast      │
        └───────────────────────────────────────────────────────────────────┘
```

### 3.1 Container inventory (Docker Compose services)
`web` (Next.js) · `api` (FastAPI: REST + WS) · `worker` (Celery, `--concurrency=10`) · `beat` (Celery Beat) · `proxy` (self-hosted rotating gateway, [§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)) · `redis` · `postgres` · `flower` (admin/ops). Single-host; **no `minio` in v1** (`StorageBackend` interface keeps it a future option).

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

**Bug fixed post-launch:** "checkpointed to Postgres immediately" originally meant one `session_scope()` (one transaction) spanning an *entire* item — SCRAPING through the terminal status. That commits only once, at the very end, so a different DB connection (the API, the dashboard) could never actually observe SCRAPING — it'd see PENDING right up until the item was already done. `worker/tasks/batch.py`'s `_process_one` now uses three short transactions per item (mark SCRAPING + commit; extract with no open transaction; persist results + terminal status + commit), publishing a WS snapshot after each commit. Confirmed via direct DB polling at 200ms resolution — SCRAPING is now genuinely visible for the item's full processing time, which is what lets the dashboard's per-item list show a real "currently scraping" indicator instead of skipping straight from pending to done.

Sketch:

```python
@celery.task(bind=True, acks_late=True, task_reject_on_worker_lost=True)
def run_batch(self, scrape_id: str):
    scrape = load_scrape(scrape_id)
    mark_running(scrape)
    exit_ip = acquire_proxy_exit(scrape)     # one exit pinned for the batch — Tier-2 only

    for item in pending_items(scrape):       # resumable: only PENDING/SCRAPING
        if is_cancelled(scrape_id):          # cooperative cancel (Redis flag)
            mark_cancelled(scrape); break

        route = resolver.route(item.url)     # per URL: (tier, egress)
        if route.tier == "api":              # Tier-1: DIRECT egress, no proxy, no jitter
            result = extract_api(item.url, scrape.config)
        else:                                # Tier-2: proxy egress + human mimicry
            jitter_sleep(1.8, 4.2)
            session = build_session(scrape, exit_ip=exit_ip)   # UA, proxy exit, cookies
            result = extract_scrape(item.url, session, scrape.config)  # yt-dlp/gallery-dl/Playwright

        persist_item_result(item, result)    # checkpoint to Postgres + write media to disk
        publish_progress(scrape_id, snapshot(scrape))        # Redis Pub/Sub → WS

    finalize(scrape)                          # COMPLETED / PARTIAL, compute totals
    publish_done(scrape_id)                   # triggers browser notification
```

**Queue routing:** a single `scrapes` queue is sufficient — the `concurrency=10` cap *is* the "10 users" limit. (If per-tenant fairness becomes an issue, upgrade to per-user rate limits or a fair-scheduling broker later; not needed for v1.)

### 4.3 Scraping core — **API-first extractor strategy**

The lawful path ([§10](#10-legal--compliance-risk)) drives the extractor order: **official APIs first, scraping only as fallback where no usable API exists.** Per URL we resolve the platform, then walk tiers top-down; **first success wins**; dedup by resolved media URL/content hash.

> **v1 launch: Tier-1 is built but inactive (decided).** We start **scrape-only for testing** — no API credentials configured means every URL falls straight through to Tier 2. The Tier-1 layer (per-platform clients, resolver dispatch) is present so it can be **switched on later per platform simply by adding credentials in admin — no redeploy, no code change**. The rest of this section describes the target behaviour once APIs are enabled.

**Tier 1 — Official platform API (preferred, ToS-compliant).** The only route that doesn't breach platform terms. Attempted first whenever credentials are configured and the API can serve the asset:
- **YouTube Data API**, **Vimeo API**, **Meta Graph API** (Instagram/Facebook), **TikTok Research/Display API**, **X API**, **Reddit API**.
- APIs are rate-limited and coverage is partial (some content/media isn't retrievable, some platforms — e.g. Snapchat — have no suitable public API). Missing/failed API access falls through to Tier 2.
- API credentials are admin-configured per platform and stored encrypted as `PlatformCredential` ([§10](#10-legal--compliance-risk)).

**Tier 2 — Fallback scraping (used only when no API is provided/usable for that platform; the *only* active path at v1 launch).** This is where legal risk concentrates and where the **self-hosted proxy gateway ([§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)) + OAuth/cookie auth** apply:
- **yt-dlp** — video (YouTube, TikTok, Vimeo, X, Facebook, Reddit video); highest-quality format (`bestvideo+bestaudio/best`).
- **gallery-dl** — image sets/carousels (Instagram, Reddit galleries, X media, Snapchat spotlight).
- **Playwright** — JS-walled / login-gated content; also the vehicle for **admin OAuth/cookie injection** (Instagram/X session) and dynamically-rendered media.
- The self-hosted proxy gateway and cookie/OAuth auth are **admin-gated, off by default**, and only ever engaged on the Tier-2 path.

Each extractor records **which tier/method served the item** (`MediaFile.source_method` = `api` \| `ytdlp` \| `gallerydl` \| `playwright`) so the audit log ([§4.7](#47-audit--lawful-use-attestation)) and per-platform health view can show the API-vs-scrape mix and where fallback is being hit.

Config toggles (`video_only`, `image_only`, `include_metadata`) filter what each tier keeps. Metadata JSON is written alongside media when enabled.

**Al Jazeera** added as a named platform post-launch (scrape-only — no public retrieval API, so it's Tier-2 by nature, not a Tier-1 candidate). yt-dlp's own `AlJazeeraIE` doesn't cover the `/video/<program>/<date>/<slug>` URL shape Al Jazeera actually uses for program episodes (its regex only matches `/videos/`, `/programs/<name>/`, `/features/`, `/news/`), which fell through to Playwright's generic DOM scrape — images only, no video. Turned out the video's Brightcove embed URL is already present in the page's own server-rendered JSON-LD (`VideoObject.embedUrl`) — no browser/click interaction needed at all. `worker/scraping/extractors/aljazeera.py` runs first in the cascade (cheap no-op domain check for every other platform), fetches the page, pulls that embed URL out, and hands it to the existing yt-dlp wrapper — which already extracts Brightcove correctly on its own; `source_method` still records `ytdlp`. Falls through to gallery-dl/Playwright as before if a page has no video embed.

### 4.4 Realtime pipeline (WebSockets)

Workers **must not** hold WebSocket connections. Flow:
1. Worker publishes a progress snapshot to Redis Pub/Sub channel `scrape:{id}`.
2. FastAPI WS process subscribes to that channel and forwards to the browser(s) watching that scrape.
3. On `done`, the frontend fires the **Web Notification API** alert.

This keeps workers stateless w.r.t. connections and lets multiple browser tabs / a reconnecting client all receive updates. WS auth via short-lived token; the unauthenticated **share-link** grants read-only WS + gallery access scoped to one scrape.

### 4.5 Storage, retention & share links
- Layout: `/data/scrapes/{scrape_id}/{category}/{filename}` — mirrors the ZIP structure, so export is a straight `zipstream` walk (no repacking, low memory).
- Share link: `share_token` (unguessable) on the `Scrape` row; unauthenticated read access to gallery + ZIP until expiry.
- **Two-layer expiry (decided — do both):**
  1. **Retention sweep** (Celery Beat, every 60s): find scrapes past `expires_at`, hard-delete the directory, null the media, invalidate `share_token`, mark `EXPIRED`. This is what actually frees disk; ≤60s tolerance on the physical delete.
  2. **Read-time gate** (defense in depth): every gallery/share/ZIP/WS read checks `now() > expires_at` and returns 410 Gone *before* touching files — so access is cut off at the exact second even if the sweep hasn't run yet. No window where expired data is still reachable.
- `expires_at = created_at + retention_hours` (retention configurable by admin).

### 4.6 Disk-full predictor (admin) — ✅ implemented (Phase 5)
Hourly Beat task (`tasks.predictor.sample_disk`). Model net disk velocity accounting for the 6h deletion cycle:
- Sample `bytes_in_per_hour` (rolling avg of recent scrape output) and `bytes_out_per_hour` (data aging past 6h and being deleted).
- `net_rate = bytes_in − bytes_out`. If `net_rate ≤ 0`: **stable, no forecast**. If `> 0`: `hours_to_full = free_bytes / net_rate`, surfaced with a confidence band and a threshold alert (e.g. warn at <24h).
- Store hourly samples in a `disk_samples` table so the admin chart shows the trend, not just a number.

Shipped without the confidence band or a <24h alert threshold — `/admin` shows the raw `hours_to_full` number (or "stable") plus the in/out rates, which is enough signal for v1. Layering on a color-coded warning threshold is a small frontend addition whenever it's actually wanted.

### 4.7 Audit & lawful-use attestation

The operator — not the tool — carries the rights ([§10](#10-legal--compliance-risk)). Two mechanisms make that concrete and defensible:

**Lawful-use attestation (gate before scrape).** Every scrape submission requires a checked **"I confirm I have the rights/lawful basis to ingest this content for editorial use"** box. The submit endpoint **rejects the batch if it is not checked** — the attestation is not decorative. We persist the exact attestation text/version, who accepted it, when, and from which IP, bound to the scrape. This is what transfers responsibility to the operator.

**Audit log (who scraped what, when).** An append-only `AuditLog` records every scrape start (and other sensitive actions: credential/cookie changes, proxy toggles, share-link access, takedowns). For each scrape start we store: actor (user id or anonymous+IP), timestamp, the submitted URLs/categories, config, the attestation record id, and the extractor tiers used. Append-only (no update/delete via app), retained beyond the 6h media window for accountability, exportable for a takedown/DSAR response.

Together these answer "who started which scrape, under what asserted rights" — the two questions a broadcaster's legal team and any complainant will ask.

### 4.8 Self-hosted proxy gateway (decided — no commercial providers)

**Decision:** ship our **own Docker-based rotating proxy gateway** as a stack service. Bright Data / Oxylabs are dropped for now; no per-GB billing to a third party. The `ProxyBackend` interface stays generic so a commercial provider *could* be plugged in later, but v1 is self-hosted only.

**Egress routing depends on scrape type — this is a hard rule, not an optimization:**

| Path | Egress | Why |
|---|---|---|
| **Tier-1 official API** | **Direct** (out the host, never the proxy) | The call is already authenticated & ToS-compliant, so there's no IP-block to dodge. Worse, routing an authenticated API token through *rotating residential exits* makes the account's requests come from constantly-changing IPs — a classic fraud/abuse signal that gets **API keys flagged or banned**. Proxying here adds risk and latency for zero benefit. |
| **Tier-2 scrape** | **Through the proxy gateway** | Unauthenticated/anti-bot-guarded fetches that *do* need IP rotation + per-batch affinity to avoid blocks. |

The **resolver** ([§4.3](#43-scraping-core--api-first-extractor-strategy)) therefore decides two things per URL together: *which extractor tier* and *which egress*. `build_session` in `run_batch` only attaches a proxy exit when the chosen path is Tier-2; a Tier-1 item runs on a direct connection with no exit assigned (`exit_ip = null` on its `UsageEvent`).

**What it is:** a `proxy` container — a rotating forward-proxy gateway (HTTP/SOCKS) that sits between the workers and the internet, **on the Tier-2 path only**. Responsibilities:
- **Exit-IP pool + rotation:** rotate among a configurable set of upstream exit endpoints.
- **Per-batch session affinity:** pin one exit IP for the lifetime of a batch (matches the anti-block model in [§4.2](#42-the-worker-queue-the-core-design) — one IP per sequential chain), rotate *across* batches.
- **Health checks + eviction** of dead/blocked exits, so a burned IP is dropped from rotation.
- **Bandwidth metering** per scrape (retained on `UsageEvent` for the disk predictor and internal accounting — **not** for provider billing anymore).

**Honest caveat on "residential":** a Docker container cannot itself *manufacture* residential IPs — the "residential" property comes from an IP living on a consumer ISP. A pure single-host deployment routes through the **host's own (datacenter/VPS) IP**, which platforms detect more easily. To get genuinely residential exits, the gateway must be **fed upstream exit nodes** the operator controls — e.g. mobile LTE modems/dongles, home endpoints, or self-hosted SOCKS/VPN exits. So the gateway's *design* is provider-agnostic rotation; the *residential quality* depends entirely on what exits you attach. This is a deliberate cost/control trade-off vs. the dropped commercial providers, and it's an operator responsibility to document ([§10](#10-legal--compliance-risk)). Admin toggle stays: proxy on/off, per-platform, off by default.

#### 4.8a Residential proxy mesh — self-registering agents — ✅ done

**The gap this closes:** `exits.yml` ([above](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)) assumes the gateway can *dial out* to a fixed, inbound-reachable `host:port` — fine for a VPS/LTE modem with a real address, but most home connections (the actual target for genuine residential exits) sit behind NAT or CGNAT with no stable reachable address at all. **Decided approach: the exit dials the gateway, not the other way around** — the same "call home" pattern real commercial residential-proxy networks use. This also makes adding exits at multiple friends'/family's homes an admin-panel operation instead of a YAML edit + redeploy.

**Transport — WebSocket over the existing HTTPS edge, deliberately not a new port.** The agent's control connection is a WebSocket to `wss://<domain>/agent/connect`, fronted by the same Nginx Proxy Manager host already terminating everything else (same pattern as the existing share-progress WS hub, [§4.4](#44-realtime-pipeline-websockets)). Consequences:
- **Zero open ports on the residential side** — purely an outbound connection, works behind NAT/CGNAT with no router configuration at all.
- **No new port on the RZ side either** — no dedicated TCP listener, no Stream/TCP passthrough host to configure in NPM; it's one more route on the domain that's already public.
- Looks like ordinary outbound HTTPS from the home network's perspective — passes through virtually any home/guest firewall.

**Relay protocol.** Because a batch is processed strictly sequentially with one exit pinned for its whole lifetime ([§4.2](#42-the-worker-queue-the-core-design)), at most one relayed connection per node is ever active at a time in practice — so this doesn't need a generic multi-stream multiplexer, just a minimal framed control protocol over the one WebSocket:
- `open {stream_id, host, port}` (gateway → agent) — request an outbound connection from the agent's home network.
- `opened {stream_id}` / `error {stream_id, message}` (agent → gateway).
- binary data frames tagged with `stream_id`, both directions.
- `close {stream_id}` either direction.

**Data model — new `ProxyNode` entity:**
```
ProxyNode   id, name, token_hash (never stores the plaintext — same one-time-reveal
            pattern as PlatformCredential secrets), priority (lower tried first),
            enabled, last_seen_at, created_at
```
Durable admin config (name/priority/enabled/token) lives here in Postgres, managed via `api`'s admin routes exactly like `Setting`/`PlatformCredential` already are. **Live state (currently connected, recent failure streak, bytes relayed) stays in the gateway process's memory** — it's the one thing actually holding the connections — and is surfaced to the admin UI the same way `/api/admin/proxy-stats` already surfaces the gateway's `/stats`. The `api` service pushes the current node/token allowlist to the gateway (a small internal, shared-secret-protected endpoint) after any admin change, so the `proxy` container never needs its own DB driver/ORM dependency.

**Priority + automatic failover (admin-configurable, replaces plain round-robin for agent exits):**
1. Only `enabled=True` **and currently connected** nodes are candidates.
2. Group by `priority` ascending; try the lowest-numbered tier first.
3. **Circuit breaker per node:** N consecutive failed relay attempts (e.g. 3) demote a node out of selection for a cooldown window (e.g. 2 minutes); a single success resets its failure count to zero immediately.
4. If every node at the current tier is disconnected/demoted, fall through to the next priority tier.
5. If nothing usable remains at any tier, fall back to direct passthrough — same honest degrade-gracefully behavior as today's empty `exits.yml`, never a hard batch failure just because residential exits are unavailable.

This directly gives "route primarily through residential #1; if it's only producing errors, fall through to #2" without any manual admin intervention when a node is having a bad day.

**Admin UI — new "Residential Nodes" page** (own nav entry alongside Settings/Credentials/CMS/Audit/Platform health): table of name / priority (editable) / live status (connected · disconnected · in-cooldown) / enabled toggle / last-seen / bytes relayed; an "add node" form that generates a token and shows it once alongside the exact `.env` snippet for the agent container.

**New/changed files:**
| File | Change |
|---|---|
| `shared/models/ops.py` (`ProxyNode`) + migration `cf8402fc4f5a` | new |
| `api/app/core/config.py` | `proxy_internal_url`, `proxy_internal_secret` |
| `api/app/schemas/admin.py` | `ProxyNodeOut/Create/Update/Created` |
| `api/app/api/routes/admin.py` | CRUD `/admin/proxy-nodes`, pushes gateway resync after every change |
| `proxy/gateway.py` | agent WS listener (`:8889`), `Exit.kind="agent"`, `AgentSession`/`AgentStream`, priority/circuit-breaker `assign_exit`, `/internal/nodes/sync`, `node_id` in `/stats` |
| `proxy/agent.py` + `Dockerfile.agent` + `requirements.agent.txt` | new — the home-side container (own lightweight image, only depends on `websockets`) |
| `web/app/admin/proxy-nodes/page.tsx` + `web/lib/adminApi.ts` additions | new |
| `docker-compose.agent.yml` + `.env.agent.example` | new — the deployment artifact for the residential machine |
| `docker-compose.yml` (`proxy` service) | `expose: ["8888", "8889"]`, `env_file: .env` (for `PROXY_INTERNAL_SECRET`) |
| `.env` / `.env.example` | `PROXY_INTERNAL_SECRET` |

**Verified with a real second container standing in for a residential machine** (not just unit-level checks): built `proxy/agent.py` into its own image, ran it alongside the stack, and drove the whole flow through the actual `api` admin routes — created a node (got a real one-time token back), connected the agent with that exact token, watched `GET /admin/proxy-nodes` flip to `connected: true` within one 10s UI poll, then sent a real HTTPS request through the gateway's plain proxy port and confirmed via `/stats` that `bytes_relayed` on that node incremented — proof the tunnel actually carries traffic, not just a control handshake. Then registered a second, lower-priority node and confirmed: a fresh session picked the higher-priority node first; killing that node's connection failed traffic over to the second automatically; and — separately — forcing 3 consecutive failures on a *still-connected* node (targeting an unresolvable host) demoted it into cooldown while it stayed nominally "connected", correctly routing subsequent traffic to the other node without any admin action. Finally, submitted a real scrape through the actual worker/`run_batch` path (not a raw curl) with only one residential node connected, and confirmed via the gateway's stats that the batch's traffic really did relay through it.

**Honest finding from that last test:** the relayed session showed up under the gateway's `"default"` session bucket rather than `session-<scrape_id>` — `session.py`'s per-batch sticky-session username isn't reliably reaching the gateway as a `Proxy-Authorization` header through every Tier-2 tool in the cascade (some of yt-dlp/gallery-dl/Playwright's own HTTP clients likely don't forward it the same way). With only one exit in the pool this doesn't matter (there's nothing to be sticky *across*), but it means per-batch exit affinity (pin one IP for a whole batch, §4.2) isn't guaranteed once there are multiple residential nodes in rotation and a single batch makes more than one request. This predates §4.8a (the same mechanism is used for static `exits.yml` entries) and wasn't something this work was scoped to fix — worth a closer look before relying on strict per-batch affinity across multiple simultaneous residential nodes.

Static `exits.yml` entries (VPS/LTE-modem-style, already inbound-reachable) keep working unchanged alongside agent-registered nodes — same exit pool, same priority/failover logic; the agent model is additive, not a replacement.

---

## 5. Data Model (core entities)

```
User            id, email, hashed_pw, is_active, is_superuser, is_verified (fastapi-users'
                structural requirements, added Phase 4), role[public|free|paid|admin],
                stripe_customer_id, credit_balance, created_at
Scrape          id, user_id (nullable for public), status, config(jsonb: video_only/…),
                share_token, total_images, total_videos, total_bytes,
                created_at, expires_at, proxy_used, ua_used
Category        id, scrape_id, name (e.g. "L1234"), order
ScrapeItem      id, scrape_id, category_id, sequence, url, platform, status, images_found,
                images_ok, videos_found, videos_ok, error, started_at, finished_at
MediaFile       id, item_id, category_id, type[image|video], path, bytes, width, height,
                duration, source_url, source_method[api|ytdlp|gallerydl|playwright],
                checksum (dedup), metadata_json
UsageEvent      id, user_id, ip, scrape_id, links_count, bytes, proxy_bytes, exit_ip,
                created_at            # proxy_bytes = internal metering only (no provider billing)
Setting         key, value        (max_links, max_scrapes_per_ip_24h, retention_hours, proxy_enabled…)
CmsPage         slug[impressum|tos|privacy], content_md, updated_at, updated_by
PlatformCredential  platform, kind[api_key|oauth_token|cookie], secret_blob(encrypted),
                added_by, valid_until, enabled          # Tier-1 API keys AND Tier-2 cookies/OAuth
LawfulAttestation   id, scrape_id, text_version, accepted (bool), actor_user_id (nullable),
                actor_ip, accepted_at                    # the transferred-rights record (§4.7)
AuditLog        id, ts, actor_user_id (nullable), actor_ip, action, target_type, target_id,
                detail(jsonb)                             # append-only; who did what, when (§4.7)
DiskSample      id, ts, free_bytes, bytes_in_rate, bytes_out_rate, hours_to_full
ProxyNode       id, name, token_hash, priority, enabled, last_seen_at, created_at (§4.8a —
                durable admin config only; live connection state stays in the gateway process)
```

Notes:
- `PlatformCredential.secret_blob` (Tier-1 API keys, Tier-2 OAuth tokens/cookies) is **encrypted at rest** ([§10](#10-legal--compliance-risk)); never exposed to non-admin users or in API responses. This replaces the earlier `AdminCookie` table and covers both API and scrape-fallback credentials.
- `LawfulAttestation` is required for every `Scrape`; a batch with `accepted = false`/absent is rejected at submit ([§4.7](#47-audit--lawful-use-attestation)). **Implementation note (deviation from the schema first sketched here):** rather than a circular `Scrape.attestation_id` ↔ `LawfulAttestation.scrape_id` FK pair, `LawfulAttestation.scrape_id` (unique) is the sole, authoritative FK; `Scrape.attestation` is just the read-side of that relationship. Avoids a same-migration circular dependency for no added value.
- `AuditLog` is **append-only** (no app-level update/delete) and outlives the 6h media window.
- `ScrapeItem.sequence` (added during Phase B implementation, not in the original sketch): UUID primary keys don't sort in submission order, and `run_batch` must process a batch's links in exactly the order pasted — `sequence` is the stable, gapless ordering key assigned at parse time.

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
├── web/                         # Next.js (plain Tailwind for now — shadcn/ui deferred, §12)
│   ├── Dockerfile
│   ├── app/
│   │   ├── page.tsx              # input form: textarea + config toggles + attestation checkbox
│   │   ├── login/, register/     # auth forms; register auto-logs in (no mailer, no verify step)
│   │   ├── account/              # profile, tier, "Upgrade to Paid", scrape history
│   │   ├── scrape/[token]/       # live dashboard: WS-driven stats, per-item status, cancel
│   │   ├── gallery/[token]/      # ALL/category/single-link scopes, multiselect, lightbox
│   │   ├── admin/                # overview (system/disk/proxy), settings, credentials, cms,
│   │   │                         # audit, platforms, proxy-nodes (§4.8a) — each page wrapped
│   │   │                         # in <AdminGuard>
│   │   └── legal/[slug]/         # public CMS render — literal text, not parsed Markdown
│   ├── components/NavBar.tsx     # login state, tier badge, conditional Admin link
│   ├── components/AdminGuard.tsx # redirects non-superusers away; renders the admin side-nav
│   ├── lib/ws.ts                 # useShareSocket: WS client, exponential-backoff reconnect,
│   │                             # treats close code 4410 (expired) as terminal, not retryable
│   ├── lib/auth.tsx              # AuthProvider/useAuth — fetches /users/me whenever a token exists
│   ├── lib/token.ts               # localStorage JWT (no framework deps — avoids an auth.tsx <-> api.ts cycle)
│   ├── lib/authErrors.ts         # maps fastapi-users' machine codes (LOGIN_BAD_CREDENTIALS, …) to text
│   ├── lib/api.ts                # fetch helpers for /api/scrapes, /api/share/*, /api/auth/*, /api/billing/*
│   └── lib/adminApi.ts           # fetch helpers for /api/admin/*, /api/cms/* — split out from api.ts
│                                  # once the admin surface got big enough to earn its own file
├── api/                         # FastAPI
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes/          # health, scrapes (submit/status/cancel/history), share (status,
│   │   │                        # categories, media list/file, export), billing (checkout/webhook),
│   │   │                        # admin (settings/credentials/disk/audit/platform-health/system/
│   │   │                        # proxy-stats — all behind current_superuser), cms (public read +
│   │   │                        # admin write); fastapi-users supplies auth/jwt, auth/register,
│   │   │                        # auth/verify, auth/reset-password, users/me — takedown lands later
│   │   ├── ws/                  # health echo + share.py — the real progress hub (§4.4):
│   │   │                        # initial snapshot on connect, then forwards Redis Pub/Sub
│   │   │                        # (progress/done) until the client disconnects
│   │   ├── schemas/              # Pydantic v2 (scrape submit/status/history, share status/media/
│   │   │                         # export, user read/create/update, admin/cms)
│   │   ├── services/             # audit.py, tasks.py (enqueue/cancel), expiry.py (410 gate —
│   │   │                         # shared by every share route), export.py (streamed ZIP),
│   │   │                         # limits.py (tier resolution + Redis rate-limit counters),
│   │   │                         # settings.py (generic Setting read/write, used by limits.py's
│   │   │                         # sibling reader, scrapes.py's retention_hours, and admin.py itself)
│   │   ├── core/                 # config, users.py (fastapi-users wiring: UserManager, JWT
│   │   │                         # backend, current_active_user[_optional], current_superuser,
│   │   │                         # ADMIN_BOOTSTRAP_EMAIL promotion), deps
│   │   └── db/                   # async session (asyncpg) + alembic env
│   └── alembic/
├── worker/                      # Celery
│   ├── Dockerfile
│   ├── celery_app.py             # broker/backend, beat_schedule, visibility_timeout (see below)
│   ├── db.py                     # sync SQLAlchemy session (psycopg) — Celery tasks stay sync
│   ├── storage.py                # write-side: checksum dedup (hardlink), category sanitization
│   ├── tasks/
│   │   ├── batch.py              # run_batch (§4.2)
│   │   ├── watchdog.py           # requeues a batch whose worker died mid-run — the actual
│   │   │                         # fast-recovery path; see the crash-resilience note below
│   │   ├── retention.py          # 6h sweep (§4.5): hard-delete dir, delete MediaFile rows,
│   │   │                         # null share_token, mark EXPIRED — Beat, 60s. Aggregate counters
│   │   │                         # are *not* zeroed (Phase 5 change) — the disk predictor and
│   │   │                         # account history both need that historical record.
│   │   └── predictor.py          # hourly disk-full forecast (§4.6): bytes_in/out rate from
│   │                              # Scrape.total_bytes, DiskSample row, Beat every 3600s
│   └── scraping/
│       ├── resolver.py           # url → platform; picks tier (API vs scrape) AND egress
│       ├── session.py            # per-batch UA + sticky proxy URL (skipped if Setting
│       │                         # proxy_enabled=false), cookie lookup/decrypt
│       └── extractors/
│           ├── cascade.py        # yt-dlp → gallery-dl → Playwright, first success wins
│           ├── ytdlp.py, gallerydl.py, playwright_extractor.py
│           └── api_stub.py       # Tier-1 extraction point — built, deliberately inactive (§12)
├── proxy/                       # self-hosted rotating proxy gateway (§4.8, §4.8a)
│   ├── Dockerfile                # gateway image (:8888 plain proxy, :8889 agent WS)
│   ├── gateway.py                # asyncio HTTP/CONNECT proxy; dial (SOCKS5) + agent (WS) exits;
│   │                             # priority + circuit-breaker assign_exit; health-check/eviction;
│   │                             # /stats, /internal/nodes/sync
│   ├── exits.example.yml         # operator-supplied static upstream exit nodes (empty by default)
│   ├── agent.py                  # §4.8a residential agent — runs on the OTHER machine, not here
│   ├── Dockerfile.agent, requirements.agent.txt  # separate, lighter image for agent.py
├── shared/                      # single source of truth for api + worker
│   ├── models/                   # SQLAlchemy (all 13 entities, §5)
│   ├── parsing.py                # category-header text parser — lives here, not under
│   │                             # worker/scraping/, since the API needs it at submit time
│   ├── crypto.py                 # Fernet encrypt/decrypt for PlatformCredential.secret_blob
│   └── storage.py                # MEDIA_ROOT + scrape_dir/delete_scrape_dir — the seam behind
│                                  # which local disk could later become S3/MinIO (§12); used by
│                                  # both worker (retention delete) and api (gallery/export reads,
│                                  # which is why api also mounts the media volume, §7)
└── docs/
    ├── ARCHITECTURE.md
    ├── DEPLOYMENT.md
    ├── PROXY.md                 # attaching upstream exits + residential caveat (§4.8)
    ├── npm-proxy-hosts.md       # NPM edge config (TLS + routing)
    └── COMPLIANCE.md            # GDPR / ToS / takedown process
```

**Crash resilience, completed (Phase B):** per-item checkpointing to Postgres (already in the §4.2 sketch) only prevents *data loss* when a worker dies — Celery's Redis broker only redelivers an orphaned message after `visibility_timeout`, which is deliberately set *longer* than the longest legitimate batch (100 links' worst-case jitter + download time) to avoid the opposite failure of two workers processing the same batch at once. Left there, recovery from a killed worker could take hours. `tasks.watchdog.requeue_stuck_batches` (Celery Beat, every 60s) closes that gap: it finds scrapes stuck `RUNNING` with no item progress for 5+ minutes and re-enqueues `run_batch` for them — safe to do because `_process_one` already skips any item in a terminal state, so this only ever resumes. Verified by killing the worker mid-batch (SIGKILL) and confirming the watchdog resumed the remaining items with no duplicate processing.

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
    volumes: ["media:/data/scrapes"]   # read-only in practice — api serves gallery/export (§4.5)
    depends_on: [postgres, redis]

  worker:
    build: ./worker
    command: celery -A celery_app worker --concurrency=10 -Q scrapes --loglevel=info
    environment:
      - <same DB/REDIS as api>
      - PROXY_GATEWAY_URL=http://proxy:8888   # Tier-2 scrape traffic routed here; APIs go direct
    volumes: ["media:/data/scrapes"]
    depends_on: [redis, postgres, proxy]
    shm_size: "1gb"                        # Chromium (Playwright) needs more than Docker's 64MB default

  proxy:                                       # self-hosted rotating gateway (§4.8)
    build: ./proxy
    expose: ["8888"]                           # internal only — never published to the host edge
    volumes: ["./proxy/exits.yml:/app/exits.yml:ro"]   # operator-supplied upstream exits
    # No commercial provider. Residential quality depends on attached exits — see §4.8.

  beat:
    build: ./worker
    command: celery -A celery_app beat --loglevel=info
    depends_on: [redis, postgres]

  flower:
    build: ./worker
    command: sh -c 'celery -A celery_app flower --port=5555 --basic_auth=$$FLOWER_BASIC_AUTH'
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

> **Note on the media volume:** `worker` writes media; `api` serves gallery/ZIP. In v1 both mount the shared `media` volume (single host) — **this was missed in the actual `docker-compose.yml` until Phase C's end-to-end testing caught it** (every share/gallery/export read failed with `FileNotFoundError` until the `api` service got the volume too). When scaling to multiple hosts, this is exactly the seam where the `StorageBackend` interface swaps local disk for MinIO/S3.

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

### Phase 1 — Acquisition engine (headless, no UI polish) — ✅ done

- Category-header **text parser** (`L1234` grouping); URL → platform **resolver**.
- `run_batch` task ([§4.2](#42-the-worker-queue-the-core-design)): sequential loop, jitter delays, UA rotation, per-item checkpointing, cancellation, resume-on-crash.
- **Tiering built, but API ships inactive** ([§4.3](#43-scraping-core--api-first-extractor-strategy)): the resolver + `ProxyBackend` + Tier-1/Tier-2 dispatch are all in place, but **v1 launches scrape-only for testing** — no API credentials configured, so every URL takes the Tier-2 path. Tier-1 activates later per platform purely by adding credentials in admin, **no redeploy**. Record `source_method` per item; config toggles; media to `/data/scrapes/...`.
- **Self-hosted proxy gateway** ([§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)): `proxy` service + `ProxyBackend` client; Tier-2 traffic routed through it with per-batch exit-IP affinity; runnable with zero exits (direct/host IP) and with operator-attached exits.
- **Attestation gate + audit log** ([§4.7](#47-audit--lawful-use-attestation)): submit rejected without accepted attestation; every scrape start written to append-only `AuditLog`. (Build the enforcement here, at the API boundary, so no path can bypass it.)
- **Exit:** a batch with a valid attestation runs **scrape-only** across 10 concurrent slots through the proxy gateway; a batch *without* attestation is rejected; audit rows recorded; media on disk in ZIP-ready layout. (Flipping on a Tier-1 API credential later must reroute that platform to the API with no code change.)

**Verified via Docker (real content, not mocks):** yt-dlp fetched a real YouTube video at full quality (4K confirmed on one run); gallery-dl fetched a real direct image; the yt-dlp → gallery-dl cascade required excluding yt-dlp's own generic extractor (it otherwise claims *any* URL is "supported" and then fails instead of deferring — see `ytdlp.py`); checksum dedup correctly hard-linked a repeated URL across two categories instead of storing it twice; the attestation gate rejected an unchecked submission (403) and the 100-link cap rejected an oversized batch (422); cancellation stopped a batch mid-chain leaving the rest `PENDING`; a `SIGKILL`'d worker's batch was correctly picked back up by `tasks.watchdog.requeue_stuck_batches` with no duplicate processing; the proxy gateway was verified both in direct-passthrough mode and — using a throwaway test SOCKS5 container — with a real upstream exit, confirming session-to-exit pinning and CONNECT tunneling both work.

### Phase 2 — Realtime dashboard — ✅ done (merged with Phase 3 into execution-plan "Phase C")
- Redis Pub/Sub → FastAPI WS hub → browser ([§4.4](#44-realtime-pipeline-websockets)).
- Input UI (textarea + toggles + **mandatory lawful-use checkbox** wired to the Phase-1 gate), top-bar stats, per-URL list with status icons + copy-link, queue position.
- Web Notification API on completion.
- **Exit:** paste links, accept attestation, watch live progress + completion notification end to end; submit is blocked if the checkbox is unchecked.

**Verified via a real Playwright browser driving the actual UI** (not just curl): submit correctly disabled until the attestation checkbox is checked; live WS-driven DOM updates observed reaching `running` then a terminal status without a page reload; browser Notification fires on completion. WS close code **4410** (a private-range app code, the WS equivalent of the HTTP 410 gate) is what the client uses to distinguish "expired, stop reconnecting" from "transient disconnect, retry with backoff."

### Phase 3 — Storage, retention, export, gallery — ✅ done
- `StorageBackend` interface (local impl); streamed ZIP export (category folders).
- Retention sweep (6h hard-delete + share-link invalidation); share-link read access.
- Gallery: ALL / category / single-link scopes, multi-select download, filtered-view ZIP, image previews + native video.
- **Exit:** share link works unauthenticated; ZIP structure correct; data provably gone at 6h.

**Verified via Docker + a real browser:** category-filtered and multi-select ZIP exports both produce correct archives (checked with Python's `zipfile`, not just an HTTP 200); a single-file endpoint serves the right `Content-Type` and honors HTTP Range (required for `<video>` seeking — `FileResponse` gives this for free); the retention sweep was run directly against a force-expired test scrape and confirmed to hard-delete the directory, delete its `MediaFile` rows, null `share_token`, zero the aggregate counters, and mark `EXPIRED`; both the HTTP 410 gate and the WS 4410 close were confirmed on that same expired scrape, and the gallery/dashboard UI renders a clean "Link expired" state rather than erroring.

**Bug found and fixed by this testing, not by inspection:** the `api` service was never given access to the `media` volume in `docker-compose.yml` — Phase A/B never needed it, since only the worker wrote files. Every share/gallery/export read failed with `FileNotFoundError` until this was added (§7's blueprint already *described* both services sharing the volume — it just hadn't been wired into the real compose file yet).

### Phase 4 — Users, tiers & monetization — ✅ done
- `fastapi-users` auth (register/verify/reset); roles.
- **Public tier**: no account; each scrape yields a dynamic share link to the *full* gallery/export (same library as paid). Gated **only** by max-URLs-per-scrape and max-scrapes-per-IP-per-24h (Redis counters keyed by IP). Registered free/paid tiers add persistent history + higher limits.
- Stripe scaffolding (Checkout, webhooks, credit/subscription framework) — products can stay in test mode.
- **Exit:** an anonymous visitor scrapes within IP limits and gets a working share-linked gallery; a registered/paid account raises the limits and keeps history.

**Implementation notes:**
- `User` (shared/models/user.py) gained `is_active`/`is_superuser`/`is_verified` and a widened `hashed_password` column — the structural shape fastapi-users' `SQLAlchemyUserDatabase` needs. It does **not** inherit fastapi-users' own base table class; verified against fastapi-users 15.0.5 that the adapter is generic over any model with matching attribute names, not an isinstance check, so `User` stays a plain member of our own `Base`/`UUIDPk`/`TimestampMixin` hierarchy.
- **No mailer wired in v1** (same "built but inactive" pattern as Tier-1 platform APIs, §12): verification and password-reset tokens are logged, not emailed. Consequently the frontend logs a user straight in after registration instead of the usual "check your email" step — there's no working email loop yet for them to complete. `is_verified` stays `False` for everyone; no route currently gates on it.
- JWT sessions last 7 days (no refresh-token flow in v1) — a deliberate simplification given the added complexity of refresh rotation wasn't worth it before Phase F's hardening pass.
- **Tier limits** (`api/app/services/limits.py`), hardcoded fallbacks until Phase E's admin UI can override them via `Setting` rows (`limits.<role>.<field>`): public 25 links/scrape, 10 scrapes/IP/24h; free 50 links/scrape, 20 scrapes/day; paid/admin the full 100-link architectural ceiling, no period cap. A rejected submission (bad attestation, too many links) never burns part of the caller's quota — the rate-limit counter only increments after those checks pass.
- **Stripe**: Checkout session creation and the webhook handler (`checkout.session.completed` → paid, `customer.subscription.deleted`/`updated` → free on cancellation) are both real code, gated by `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` — undefined in this dev environment, so both routes return 503 rather than crash (§12's "wired but inactive" pattern again). The **webhook handler's logic** was verified for real by constructing locally-HMAC-signed test events (Stripe's signature scheme needs no live account to test) and confirming a user actually flips PAID→FREE in the DB, plus that a bad signature is correctly rejected with 400. The **Checkout-session-creation call itself** was not exercised against Stripe's real API — no live keys exist — so that specific path is unverified beyond "returns 503 when unconfigured."
- **Bug found by this testing:** newer `stripe` (15.3.0) returns `event["data"]["object"]` as a `StripeObject`, not a plain dict — `.get()` raises `AttributeError` rather than returning `None`. Fixed by switching to `getattr(data, field, None)`.
- **Bug found and fixed, pre-existing since Phase C:** `ScrapeStatusResponse.share_token` was typed as a non-nullable `str`, but `Scrape.share_token` became nullable back in Phase C (the retention sweep nulls it). Any expired scrape queried via `GET /api/scrapes/{id}` would have failed Pydantic response validation with a 500. Found while adding the history schema, fixed to `str | None`.

**Verified via a real Playwright browser:** register → auto-login → empty history on `/account`; log out → submit anonymously (public tier) → succeeds; log back in → wrong password shows a friendly "Incorrect email or password." (not the raw `LOGIN_BAD_CREDENTIALS` code fastapi-users returns) → correct password succeeds; submit while authenticated → the scrape is attributed to the user and appears in `/account`'s history with working Dashboard/Gallery links. Tier differentiation confirmed directly against the API: 30 links rejected for an anonymous submitter (max 25) but accepted for a free-tier account (max 50); the 24h rate limit confirmed by temporarily overriding `limits.public.max_scrapes_per_period` down to 1 via a `Setting` row and observing the second anonymous submission get 429.

### Phase 5 — Admin dashboard — ✅ done
- Live IO/CPU/disk (host metrics); Flower behind admin auth.
- **Disk-full predictor** ([§4.6](#46-disk-full-predictor-admin)) with trend chart.
- Settings (limits, retention); CMS for Impressum/ToS/Privacy; **encrypted `PlatformCredential` UI** for Tier-1 API keys *and* Tier-2 OAuth/cookies; **self-hosted proxy toggle** (on/off per platform) + exit-pool health view + internal bandwidth metering ([§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)).
- **Audit log viewer** (search/export who-scraped-what) and **per-platform health** incl. the API-vs-fallback mix (`source_method`).
- **Exit:** admin can tune limits, edit legal pages, add API keys/cookies, read the disk forecast, and query the audit log.

**Implementation notes:**
- **Admin gate** = fastapi-users' own `is_superuser` flag (`current_superuser` dependency), not a separate concept from the existing `role` enum — both get set together. Since there's no admin panel yet to promote the *first* admin, `ADMIN_BOOTSTRAP_EMAIL` promotes a matching email to `is_superuser=True, role=ADMIN` the moment it registers; anyone promoted after that goes through the admin panel itself (`PATCH` isn't built for user-role management yet — deferred, see open decisions).
- **Proxy toggle** turned out to be global, not per-platform, once actually implemented: re-reading §5's own data-model comment ("Setting key, value (…, proxy_enabled…)") confirms a single kill-switch was always the intent, not a per-platform table. A `proxy_enabled` Setting (default on) is checked once per batch when `BatchSession` is built; off routes every Tier-2 request in that batch direct instead of through the gateway.
- **Retention behavior changed**: `tasks/retention.py` no longer zeroes `total_images`/`total_videos`/`total_bytes` on expiry (a Phase C behavior). Two things needed that historical record: the disk predictor's `bytes_out_rate` (how much data left the system by expiring) and the account history page reading better showing what a scrape *had* rather than silently zeroing it under the user. Only the physical files and `MediaFile` rows are actually gone after expiry now — the aggregate counters are a frozen historical snapshot.
- **Disk predictor** samples hourly: `bytes_in_rate` = `total_bytes` summed over scrapes *created* in the last hour; `bytes_out_rate` = `total_bytes` summed over scrapes the retention sweep *expired* in the last hour (only possible because of the retention change above). `hours_to_full` is only set when the net rate is positive — a net rate at or below zero reports "stable" rather than a nonsensical negative ETA.
- **CMS slugs are an open list**, not the fixed impressum/tos/privacy three originally sketched in §5 — an operator can create more legal pages later without a schema change. Rendered as literal text on the public `/legal/[slug]` page, not parsed Markdown-to-HTML — adding a Markdown renderer for what is, in v1, an admin-trusted textarea felt like unnecessary weight; worth revisiting if CMS content gets more elaborate.
- **System/disk metrics** run from inside the `api` container via `psutil` + `shutil.disk_usage` — correct for the disk metric specifically because `MEDIA_ROOT` is a real mounted volume reflecting genuine host disk capacity; CPU/memory readings reflect whatever `psutil` sees inside the container's cgroup (host-wide here, since no resource limits are set on these containers yet).

**Verified via a real Playwright browser (plus direct DB checks for the more precise assertions):** the bootstrap admin got `is_superuser` and could reach `/admin`; a second, regularly-registered account was correctly bounced back to `/` on the same URL. A `limits.public.max_links_per_scrape` override saved and listed correctly. Adding an *enabled* `youtube` credential via `/admin/credentials` and then submitting a YouTube URL produced a `FAILED` item whose error was **exactly** `api_stub.py`'s "Tier-1 API extraction … is not implemented yet" message — direct proof the credential flipped `resolver.route()`'s tier decision from scrape to API, cross-checked against the same URL's *prior* `SUCCESS` rows (via yt-dlp, Tier-2) from before any credential existed. Editing the `impressum` CMS page and then loading `/legal/impressum` showed the saved text. The audit log and per-platform health views rendered real accumulated data across every phase's testing (54 items on unrecognized test domains, 7 on youtube: 6 historical Tier-2 successes + the 1 fresh Tier-1 failure). The disk-full predictor was triggered manually (real hourly cadence being too slow to wait out) and produced a correct sample — free space read from the real mounted volume, `hours_to_full` correctly `null`/"stable" since net rate was ≤ 0. Flower's basic auth was confirmed to reject no-credential and wrong-credential requests with 401 and accept the right ones with 200.

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
- ✅ **Exactly 6h** = do both — 60s retention sweep *and* read-time `now() > expires_at` gate ([§4.5](#45-storage-retention--share-links)).
- ✅ **Proxy** = own Docker rotating gateway, no commercial provider ([§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)); `ProxyBackend` iface keeps a provider swappable later.
- ✅ **Single-host** = yes; local-disk storage behind `StorageBackend`, **MinIO not built in v1**.
- ✅ **API activation** = v1 ships **scrape-only for testing**; Tier-1 APIs built but inactive, enabled later per platform via admin credentials, no redeploy ([§4.3](#43-scraping-core--api-first-extractor-strategy)).

**Still open:**
1. **Which platforms get a Tier-1 API client first**, once we move past scrape-only testing. Suggested order when enabling: YouTube, Vimeo (well-documented, media-retrievable); then Meta/TikTok/X/Reddit as credentials/approval land; Snapchat stays scrape-only (no suitable API).
2. **Attestation wording**: the exact legal text of the lawful-use checkbox needs counsel sign-off (versioned in `LawfulAttestation.text_version`).
3. **Upstream proxy exits**: what exit nodes the operator attaches to the gateway (LTE modems / home endpoints / SOCKS/VPN) — determines the real "residential" quality ([§4.8](#48-self-hosted-proxy-gateway-decided--no-commercial-providers)); pure single-host = host/datacenter IP.
4. **shadcn/ui**: Phase C shipped the frontend with plain Tailwind (no shadcn/ui components) to keep scope on functional correctness — every page/interaction was verified with a real Playwright browser instead. Adopting shadcn/ui for visual polish is still open and can happen incrementally, component by component, without touching the data-fetching/WS logic.
5. **Mailer**: Phase 4 shipped auth with no SMTP wired — verification/reset tokens are logged, not emailed, and the frontend auto-logs a user in after registration rather than making them complete a verification step that has nowhere to send its email yet. Wiring a real transactional-email provider (and then actually gating login on `is_verified`) is Phase F territory.
6. **JWT refresh**: v1 uses a single 7-day access token with no refresh-token rotation — simplest thing that works; revisit if session length or revocation-on-demand becomes a real requirement.
7. **Stripe**: no live account/keys exist for this project yet. The webhook handler's event-processing logic is verified (locally-signed test events); Checkout-session creation is real code but has never been exercised against Stripe's actual API. Needs a real test-mode Stripe account + `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`/`STRIPE_PRICE_ID` before launch.
8. **Promoting admins after the first one**: `ADMIN_BOOTSTRAP_EMAIL` only seeds the very first admin, on registration. There's no "make this existing user an admin" UI yet — for now that's a direct DB update (`UPDATE users SET is_superuser=true, role='ADMIN' WHERE email=...`). A small admin-panel affordance for this is easy to add whenever it's actually needed.
9. **CMS rendering**: `/legal/[slug]` renders `content_md` as literal preformatted text, not parsed Markdown-to-HTML. Fine for short legal text typed by a trusted admin; revisit if CMS content needs real formatting (headings, links, lists).
10. **Flower's default credentials**: `.env.example` ships `FLOWER_BASIC_AUTH=admin:changeme` as a visible placeholder — change it (and `ADMIN_BOOTSTRAP_EMAIL`/`SECRET_KEY`/`CREDENTIAL_ENCRYPTION_KEY`) before any non-local deployment. None of these are secret-scanned or enforced-different-from-default anywhere yet.
11. **Residential proxy mesh** ([§4.8a](#48a-residential-proxy-mesh--self-registering-agents--done)): built and verified with a real second container standing in for a residential machine. Open follow-up: per-batch sticky-session affinity (§4.2) isn't reliably reaching the gateway through every Tier-2 tool in the cascade — harmless with a single exit, but worth fixing before relying on strict per-batch IP affinity across multiple simultaneous residential nodes.
12. **Agent reconnection has no backoff cap**: `proxy/agent.py` retries every 5s forever on any disconnect (including auth failure after a node is deleted/disabled) — fine for now, but a deleted-and-forgotten agent container will log a warning every 5s indefinitely. Exponential backoff (capped) would be a small, easy improvement.
