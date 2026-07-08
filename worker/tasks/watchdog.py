"""Requeues batches whose worker died mid-run (PLAN.md §4.2 crash resilience).

Per-item checkpointing to Postgres already guarantees no data is lost when a
worker is killed — but Celery's Redis broker only redelivers an orphaned
message after `visibility_timeout` (intentionally kept *longer* than the
longest legitimate batch here, to avoid the opposite failure: two workers
processing the same batch at once because a slow-but-alive task looked
"lost"). Left alone, that means an hours-long wait to actually resume.

This Beat-scheduled task closes that gap: it looks for scrapes stuck in
RUNNING with no item progress for a while and re-enqueues run_batch for
them. Re-entering run_batch is safe — _process_one skips any item that's
already in a terminal state, so this only ever resumes, never re-does work.
"""

import logging
from datetime import datetime, timedelta, timezone

from celery_app import celery_app
from db import session_scope

from shared.models import Scrape, ScrapeItem
from shared.models.enums import ScrapeItemStatus, ScrapeStatus

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=5)


@celery_app.task(name="tasks.watchdog.requeue_stuck_batches")
def requeue_stuck_batches() -> int:
    requeued = 0
    now = datetime.now(timezone.utc)

    with session_scope() as db:
        running = db.query(Scrape).filter(Scrape.status == ScrapeStatus.RUNNING).all()
        for scrape in running:
            last_activity = (
                db.query(ScrapeItem.finished_at)
                .filter(ScrapeItem.scrape_id == scrape.id, ScrapeItem.finished_at.isnot(None))
                .order_by(ScrapeItem.finished_at.desc())
                .limit(1)
                .scalar()
            ) or scrape.created_at

            if now - last_activity < STALE_AFTER:
                continue

            still_pending = (
                db.query(ScrapeItem)
                .filter(
                    ScrapeItem.scrape_id == scrape.id,
                    ScrapeItem.status.in_([ScrapeItemStatus.PENDING, ScrapeItemStatus.SCRAPING]),
                )
                .count()
            )
            if still_pending == 0:
                continue  # everything's terminal; run_batch just hasn't finalized yet — leave it

            logger.warning(
                "scrape %s stuck in RUNNING with no progress since %s — requeueing", scrape.id, last_activity
            )
            celery_app.send_task("tasks.batch.run_batch", args=[str(scrape.id)], queue="scrapes")
            requeued += 1

    return requeued
