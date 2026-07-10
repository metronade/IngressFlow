"""run_batch: one Celery task per scrape batch, iterating its links
sequentially (PLAN.md §4.2). Concurrency across batches comes entirely from
`--concurrency=10` on the worker command — this task only ever processes one
batch, one link at a time, in submission order.
"""

import json
import logging
import os
import random
import shutil
import tempfile
import time
from datetime import datetime, timezone

import redis as redis_lib
from celery_app import celery_app
from db import session_scope
from scraping import session as scraping_session
from scraping.extractors import api_stub
from scraping.extractors.cascade import run_tier2
from scraping.resolver import route
from storage import persist_media

from shared.models import PlatformCredential, Scrape, ScrapeItem
from shared.models.enums import CredentialKind, ScrapeItemStatus, ScrapeStatus

logger = logging.getLogger(__name__)

JITTER_MIN, JITTER_MAX = 1.8, 4.2

_TERMINAL = (ScrapeItemStatus.SUCCESS, ScrapeItemStatus.PARTIAL, ScrapeItemStatus.FAILED)

_redis = redis_lib.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))


def _cancel_key(scrape_id: str) -> str:
    return f"scrape:{scrape_id}:cancelled"


def is_cancelled(scrape_id: str) -> bool:
    return _redis.get(_cancel_key(scrape_id)) is not None


def _publish(scrape_id: str, event: dict) -> None:
    try:
        _redis.publish(f"scrape:{scrape_id}:progress", json.dumps(event, default=str))
    except redis_lib.RedisError:
        logger.warning("progress publish failed for scrape %s", scrape_id, exc_info=True)


def _snapshot(db, scrape: Scrape) -> dict:
    total = db.query(ScrapeItem).filter(ScrapeItem.scrape_id == scrape.id).count()
    done = (
        db.query(ScrapeItem)
        .filter(ScrapeItem.scrape_id == scrape.id, ScrapeItem.status.in_(_TERMINAL))
        .count()
    )
    return {
        "scrape_id": str(scrape.id),
        "status": scrape.status.value,
        "links_done": done,
        "links_total": total,
        "total_images": scrape.total_images,
        "total_videos": scrape.total_videos,
        "total_bytes": scrape.total_bytes,
    }


def _enabled_api_platforms(db) -> set[str]:
    rows = (
        db.query(PlatformCredential.platform)
        .filter(
            PlatformCredential.enabled.is_(True),
            PlatformCredential.kind.in_([CredentialKind.API_KEY, CredentialKind.OAUTH_TOKEN]),
        )
        .all()
    )
    return {r[0] for r in rows}


def _publish_snapshot(scrape_id: str) -> None:
    with session_scope() as db:
        scrape = db.get(Scrape, scrape_id)
        _publish(scrape_id, _snapshot(db, scrape))


def _process_one(
    scrape_id: str,
    item_id: str,
    batch_session: scraping_session.BatchSession,
    enabled_api_platforms: set[str],
    work_dir: str,
) -> str:
    """Processes one link end to end, checkpointing to Postgres immediately
    (PLAN.md §4.2's crash-resilience requirement). Returns "processed",
    "skipped" (already terminal — a resumed run), or "cancelled".

    Split into separate short-lived transactions rather than one spanning
    the whole item: the SCRAPING transition has to actually commit — and
    become visible to a *different* DB connection (the API, the dashboard)
    — before the (potentially slow) extraction runs. A single transaction
    for the whole item means SCRAPING and the terminal status both land in
    the same commit, so nobody ever observes "scraping" at all — which is
    exactly what was happening before this split.
    """
    with session_scope() as db:
        item = db.get(ScrapeItem, item_id)
        if item.status not in (ScrapeItemStatus.PENDING, ScrapeItemStatus.SCRAPING):
            return "skipped"
        if is_cancelled(scrape_id):
            return "cancelled"

        scrape = db.get(Scrape, scrape_id)
        config = scrape.config or {}
        url = item.url
        category_id = item.category_id
        category_name = item.category.name

        route_result = route(url, enabled_api_platforms)
        item.platform = route_result.platform
        item.status = ScrapeItemStatus.SCRAPING
        item.started_at = datetime.now(timezone.utc)

    _publish_snapshot(scrape_id)

    try:
        if route_result.tier == "api":
            # Unreachable in v1 (enabled_api_platforms is always empty
            # until an admin enables a credential) — see api_stub.py.
            result = api_stub.extract(url, platform=route_result.platform, config=config)
        else:
            with session_scope() as db:
                cookie_file = scraping_session.cookie_file_for(db, route_result.platform)
            try:
                result = run_tier2(
                    url,
                    user_agent=batch_session.user_agent,
                    proxy_url=batch_session.proxy_url,
                    cookie_file=cookie_file,
                    work_dir=work_dir,
                    config=config,
                )
            finally:
                if cookie_file:
                    os.remove(cookie_file)
    except Exception as exc:  # noqa: BLE001 — a per-item failure, the batch continues
        with session_scope() as db:
            item = db.get(ScrapeItem, item_id)
            item.status = ScrapeItemStatus.FAILED
            item.error = str(exc)[:2000]
            item.finished_at = datetime.now(timezone.utc)
        _publish_snapshot(scrape_id)
        return "processed"

    with session_scope() as db:
        item = db.get(ScrapeItem, item_id)
        scrape = db.get(Scrape, scrape_id)

        images_found = sum(1 for m in result.media if m.type == "image")
        videos_found = sum(1 for m in result.media if m.type == "video")
        images_ok = videos_ok = 0
        any_save_failed = False

        for media in result.media:
            if config.get("video_only") and media.type == "image":
                continue
            if config.get("image_only") and media.type == "video":
                continue
            try:
                media_file = persist_media(
                    db,
                    scrape_id=scrape_id,
                    item_id=item.id,
                    category_id=category_id,
                    category_name=category_name,
                    extracted=media,
                    source_method=result.source_method,
                    source_url=url,
                    include_metadata=bool(config.get("include_metadata")),
                )
            except OSError:
                any_save_failed = True
                logger.warning("failed to persist media for item %s", item.id, exc_info=True)
                continue

            if media.type == "image":
                images_ok += 1
            else:
                videos_ok += 1
            scrape.total_bytes += media_file.bytes

        item.images_found = images_found
        item.images_ok = images_ok
        item.videos_found = videos_found
        item.videos_ok = videos_ok
        item.finished_at = datetime.now(timezone.utc)
        if any_save_failed and images_ok + videos_ok == 0:
            item.status = ScrapeItemStatus.FAILED
        elif any_save_failed:
            item.status = ScrapeItemStatus.PARTIAL
        else:
            item.status = ScrapeItemStatus.SUCCESS

        scrape.total_images += images_ok
        scrape.total_videos += videos_ok

    _publish_snapshot(scrape_id)
    return "processed"


@celery_app.task(name="tasks.batch.run_batch", bind=True, acks_late=True, task_reject_on_worker_lost=True)
def run_batch(self, scrape_id: str) -> None:
    work_dir = tempfile.mkdtemp(prefix="ingressflow-")
    try:
        with session_scope() as db:
            scrape = db.get(Scrape, scrape_id)
            if scrape is None:
                logger.error("scrape %s not found", scrape_id)
                return

            scrape.status = ScrapeStatus.RUNNING
            batch_session = scraping_session.BatchSession(scrape_id, db)
            scrape.proxy_used = batch_session.proxy_url is not None
            scrape.ua_used = batch_session.user_agent

            enabled_api_platforms = _enabled_api_platforms(db)
            item_ids = [
                row[0]
                for row in db.query(ScrapeItem.id)
                .filter(ScrapeItem.scrape_id == scrape_id)
                .order_by(ScrapeItem.sequence)
                .all()
            ]

        cancelled = False
        for item_id in item_ids:
            outcome = _process_one(scrape_id, item_id, batch_session, enabled_api_platforms, work_dir)
            if outcome == "cancelled":
                cancelled = True
                break
            if outcome == "processed":
                time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))

        with session_scope() as db:
            scrape = db.get(Scrape, scrape_id)
            if cancelled:
                scrape.status = ScrapeStatus.CANCELLED
            else:
                statuses = {
                    s for (s,) in db.query(ScrapeItem.status).filter(ScrapeItem.scrape_id == scrape_id).all()
                }
                scrape.status = (
                    ScrapeStatus.COMPLETED if statuses <= {ScrapeItemStatus.SUCCESS} else ScrapeStatus.PARTIAL
                )
            db.flush()
            _publish(scrape_id, _snapshot(db, scrape))
            _redis.publish(f"scrape:{scrape_id}:done", "1")
    except Exception:
        with session_scope() as db:
            scrape = db.get(Scrape, scrape_id)
            if scrape is not None:
                scrape.status = ScrapeStatus.FAILED
        logger.exception("run_batch fatal error for scrape %s", scrape_id)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _redis.delete(_cancel_key(scrape_id))
