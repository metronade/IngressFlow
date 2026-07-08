"""6-hour retention sweep (PLAN.md §4.5) — one half of the two-layer expiry
decision (the other half is the api's read-time 410 gate). Runs every 60s
via Celery Beat: past-expiry scrapes get their disk directory hard-deleted,
their MediaFile rows removed, their share_token nulled (defense in depth —
the read-time gate already blocks access by expires_at/status alone), and
are marked EXPIRED.

Deliberately does *not* zero total_images/total_videos/total_bytes anymore
(a Phase C behavior, changed here in Phase 5): the disk-full predictor
(§4.6, tasks/predictor.py) needs a "bytes_out" rate — how much data left
the system by expiring — and the account history page reads better showing
what a scrape *had* rather than silently zeroing it out from under the
user. The numbers are historical from this point on; only the physical
bytes and DB media rows are actually gone.
"""

import logging
from datetime import datetime, timezone

from celery_app import celery_app
from db import session_scope

from shared.models import MediaFile, Scrape, ScrapeItem
from shared.models.enums import ScrapeStatus
from shared.storage import delete_scrape_dir

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.retention.sweep_expired")
def sweep_expired() -> int:
    now = datetime.now(timezone.utc)
    swept = 0

    with session_scope() as db:
        expired = (
            db.query(Scrape)
            .filter(Scrape.expires_at < now, Scrape.status != ScrapeStatus.EXPIRED)
            .all()
        )
        for scrape in expired:
            delete_scrape_dir(scrape.id)

            item_ids = db.query(ScrapeItem.id).filter(ScrapeItem.scrape_id == scrape.id).subquery()
            db.query(MediaFile).filter(MediaFile.item_id.in_(item_ids)).delete(synchronize_session=False)

            scrape.status = ScrapeStatus.EXPIRED
            scrape.share_token = None
            swept += 1
            logger.info("expired scrape %s (past %s)", scrape.id, scrape.expires_at)

    return swept
