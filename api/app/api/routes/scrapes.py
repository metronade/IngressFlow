import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.scrape import (
    ScrapeItemStatusOut,
    ScrapeStatusResponse,
    ScrapeSubmitRequest,
    ScrapeSubmitResponse,
)
from app.services.audit import write_audit
from app.services.tasks import enqueue_run_batch, request_cancel
from shared.models import Category, LawfulAttestation, Scrape, ScrapeItem
from shared.models.enums import ScrapeStatus
from shared.parsing import parse_batch

router = APIRouter()

# Hard architectural limit from PLAN.md §1 (the sequential-chain design),
# not a monetization tier — per-tier limits land on top of this in Phase D
# via the Setting table.
MAX_LINKS_PER_BATCH = 100
DEFAULT_RETENTION_HOURS = 6


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/scrapes", response_model=ScrapeSubmitResponse, status_code=201)
async def submit_scrape(
    payload: ScrapeSubmitRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> ScrapeSubmitResponse:
    if not payload.attestation.accepted:
        # PLAN.md §4.7 — rejecting an unchecked attestation here, at the
        # submit boundary, is what transfers responsibility to the operator.
        # It is not decorative: no scrape row is created without it.
        raise HTTPException(
            status_code=403,
            detail="You must confirm you hold the rights/lawful basis to ingest this content.",
        )

    parsed = parse_batch(payload.raw_text)
    if parsed.total_links == 0:
        raise HTTPException(status_code=422, detail="No URLs found in the pasted text.")
    if parsed.total_links > MAX_LINKS_PER_BATCH:
        raise HTTPException(
            status_code=422,
            detail=f"Batch exceeds the {MAX_LINKS_PER_BATCH}-link limit ({parsed.total_links} links found).",
        )

    ip = _client_ip(request)
    now = datetime.now(timezone.utc)

    scrape = Scrape(
        status=ScrapeStatus.QUEUED,
        config=payload.config.model_dump(),
        share_token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(hours=DEFAULT_RETENTION_HOURS),
    )
    db.add(scrape)
    await db.flush()

    sequence = 0
    for order, cat in enumerate(parsed.categories):
        category = Category(scrape_id=scrape.id, name=cat.name, order=order)
        db.add(category)
        await db.flush()
        for url in cat.urls:
            db.add(ScrapeItem(scrape_id=scrape.id, category_id=category.id, sequence=sequence, url=url))
            sequence += 1

    db.add(
        LawfulAttestation(
            scrape_id=scrape.id,
            text_version=payload.attestation.text_version,
            accepted=True,
            actor_ip=ip,
            accepted_at=now,
        )
    )

    write_audit(
        db,
        actor_ip=ip,
        action="scrape.submitted",
        target_type="scrape",
        target_id=scrape.id,
        detail={
            "links_total": parsed.total_links,
            "categories": [c.name for c in parsed.categories],
            "config": payload.config.model_dump(),
        },
    )

    await db.commit()

    enqueue_run_batch(str(scrape.id))

    return ScrapeSubmitResponse(
        scrape_id=scrape.id,
        share_token=scrape.share_token,
        status=scrape.status.value,
        links_total=parsed.total_links,
    )


@router.get("/scrapes/{scrape_id}", response_model=ScrapeStatusResponse)
async def get_scrape(scrape_id: str, db: AsyncSession = Depends(get_db)) -> ScrapeStatusResponse:
    scrape = await db.get(Scrape, scrape_id)
    if scrape is None:
        raise HTTPException(status_code=404, detail="Scrape not found")

    result = await db.execute(
        select(ScrapeItem).filter(ScrapeItem.scrape_id == scrape.id).order_by(ScrapeItem.sequence)
    )
    items = result.scalars().all()

    return ScrapeStatusResponse(
        scrape_id=scrape.id,
        status=scrape.status.value,
        total_images=scrape.total_images,
        total_videos=scrape.total_videos,
        total_bytes=scrape.total_bytes,
        share_token=scrape.share_token,
        items=[
            ScrapeItemStatusOut(
                id=i.id,
                url=i.url,
                platform=i.platform,
                status=i.status.value,
                images_found=i.images_found,
                images_ok=i.images_ok,
                videos_found=i.videos_found,
                videos_ok=i.videos_ok,
                error=i.error,
            )
            for i in items
        ],
    )


@router.post("/scrapes/{scrape_id}/cancel", status_code=202)
async def cancel_scrape(scrape_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    scrape = await db.get(Scrape, scrape_id)
    if scrape is None:
        raise HTTPException(status_code=404, detail="Scrape not found")

    await request_cancel(str(scrape.id))

    write_audit(
        db,
        actor_ip=_client_ip(request),
        action="scrape.cancel_requested",
        target_type="scrape",
        target_id=scrape.id,
    )
    await db.commit()
    return {"status": "cancel_requested"}
