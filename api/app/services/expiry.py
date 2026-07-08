"""Read-time expiry gate (PLAN.md §4.5) — the second of the two-layer
expiry design. The retention sweep (worker, every 60s) is what actually
frees disk; this gate is defense in depth so a share link is refused the
instant it's past expires_at, without waiting for the sweep to run."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Scrape
from shared.models.enums import ScrapeStatus


async def get_active_scrape_by_token(token: str, db: AsyncSession) -> Scrape:
    result = await db.execute(select(Scrape).filter(Scrape.share_token == token))
    scrape = result.scalar_one_or_none()

    if (
        scrape is None
        or scrape.status == ScrapeStatus.EXPIRED
        or scrape.expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=410, detail="This share link has expired or does not exist.")

    return scrape
