"""Hourly disk-full predictor (PLAN.md §4.6). Samples current free space on
the media volume plus the last hour's scrape velocity, and forecasts
hours_to_full only when the net rate is actually positive (filling up) —
a net rate at or below zero means the 6h deletion cycle is keeping pace,
which is reported as stable rather than a nonsensical negative ETA.

bytes_in: total_bytes summed over scrapes *created* in the last hour.
bytes_out: total_bytes summed over scrapes the retention sweep *expired* in
the last hour — this only works because retention.py stopped zeroing
total_bytes on expiry (Phase 5 change); those totals are the historical
record this task depends on.
"""

import logging
import shutil
from datetime import datetime, timedelta, timezone

from celery_app import celery_app
from db import session_scope
from sqlalchemy import func

from shared.models import DiskSample, Scrape
from shared.models.enums import ScrapeStatus
from shared.storage import MEDIA_ROOT

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.predictor.sample_disk")
def sample_disk() -> dict:
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    free_bytes = shutil.disk_usage(MEDIA_ROOT).free

    with session_scope() as db:
        bytes_in_rate = float(
            db.query(func.coalesce(func.sum(Scrape.total_bytes), 0))
            .filter(Scrape.created_at >= one_hour_ago)
            .scalar()
        )
        bytes_out_rate = float(
            db.query(func.coalesce(func.sum(Scrape.total_bytes), 0))
            .filter(
                Scrape.status == ScrapeStatus.EXPIRED,
                Scrape.expires_at >= one_hour_ago,
                Scrape.expires_at < now,
            )
            .scalar()
        )

        net_rate = bytes_in_rate - bytes_out_rate
        hours_to_full = (free_bytes / net_rate) if net_rate > 0 else None

        db.add(
            DiskSample(
                ts=now,
                free_bytes=free_bytes,
                bytes_in_rate=bytes_in_rate,
                bytes_out_rate=bytes_out_rate,
                hours_to_full=hours_to_full,
            )
        )

    logger.info(
        "disk sample: free=%d bytes_in_rate=%.0f bytes_out_rate=%.0f hours_to_full=%s",
        free_bytes,
        bytes_in_rate,
        bytes_out_rate,
        hours_to_full,
    )
    return {"free_bytes": free_bytes, "hours_to_full": hours_to_full}
