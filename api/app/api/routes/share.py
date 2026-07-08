import mimetypes
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.share import (
    CategoryOut,
    ExportSelectionRequest,
    MediaFileOut,
    ShareItemOut,
    ShareStatusResponse,
)
from app.services.expiry import get_active_scrape_by_token
from app.services.export import stream_export
from shared.models import Category, MediaFile, ScrapeItem

router = APIRouter(prefix="/share/{token}")


@router.get("", response_model=ShareStatusResponse)
async def get_share_status(token: str, db: AsyncSession = Depends(get_db)) -> ShareStatusResponse:
    scrape = await get_active_scrape_by_token(token, db)

    result = await db.execute(
        select(ScrapeItem).filter(ScrapeItem.scrape_id == scrape.id).order_by(ScrapeItem.sequence)
    )
    items = result.scalars().all()

    return ShareStatusResponse(
        scrape_id=scrape.id,
        status=scrape.status.value,
        total_images=scrape.total_images,
        total_videos=scrape.total_videos,
        total_bytes=scrape.total_bytes,
        expires_at=scrape.expires_at,
        items=[
            ShareItemOut(
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


@router.get("/categories", response_model=list[CategoryOut])
async def get_share_categories(token: str, db: AsyncSession = Depends(get_db)) -> list[CategoryOut]:
    scrape = await get_active_scrape_by_token(token, db)

    result = await db.execute(
        select(Category).filter(Category.scrape_id == scrape.id).order_by(Category.order)
    )
    return [CategoryOut(id=c.id, name=c.name, order=c.order) for c in result.scalars().all()]


async def _scoped_media(
    db: AsyncSession, scrape_id, category_id: UUID | None, item_id: UUID | None
) -> list[tuple[MediaFile, Category]]:
    query = (
        select(MediaFile, Category)
        .join(ScrapeItem, MediaFile.item_id == ScrapeItem.id)
        .join(Category, MediaFile.category_id == Category.id)
        .filter(ScrapeItem.scrape_id == scrape_id)
    )
    if item_id is not None:
        query = query.filter(MediaFile.item_id == item_id)
    elif category_id is not None:
        query = query.filter(MediaFile.category_id == category_id)

    result = await db.execute(query)
    return list(result.all())


@router.get("/media", response_model=list[MediaFileOut])
async def get_share_media(
    token: str,
    category_id: UUID | None = None,
    item_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[MediaFileOut]:
    scrape = await get_active_scrape_by_token(token, db)
    rows = await _scoped_media(db, scrape.id, category_id, item_id)

    return [
        MediaFileOut(
            id=m.id,
            item_id=m.item_id,
            category_id=m.category_id,
            category_name=cat.name,
            type=m.type.value,
            bytes=m.bytes,
            width=m.width,
            height=m.height,
            duration=m.duration,
            source_url=m.source_url,
            source_method=m.source_method.value,
        )
        for m, cat in rows
    ]


@router.get("/media/{media_id}/file")
async def get_share_media_file(token: str, media_id: UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    scrape = await get_active_scrape_by_token(token, db)

    result = await db.execute(
        select(MediaFile)
        .join(ScrapeItem, MediaFile.item_id == ScrapeItem.id)
        .filter(ScrapeItem.scrape_id == scrape.id, MediaFile.id == media_id)
    )
    media = result.scalar_one_or_none()
    if media is None or not os.path.exists(media.path):
        raise HTTPException(status_code=404, detail="Media file not found")

    content_type = mimetypes.guess_type(media.path)[0] or "application/octet-stream"
    # FileResponse supports HTTP Range out of the box — required for native
    # <video> seeking, not just a nice-to-have (PLAN.md §3's gallery spec).
    return FileResponse(media.path, media_type=content_type)


@router.get("/export")
async def export_scoped(
    token: str,
    category_id: UUID | None = None,
    item_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    scrape = await get_active_scrape_by_token(token, db)
    rows = await _scoped_media(db, scrape.id, category_id, item_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No media matches this view")

    pairs = [(m, cat.name) for m, cat in rows]
    return StreamingResponse(
        stream_export(pairs),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{scrape.id}.zip"'},
    )


@router.post("/export")
async def export_selected(
    token: str, payload: ExportSelectionRequest, db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    scrape = await get_active_scrape_by_token(token, db)
    if not payload.media_ids:
        raise HTTPException(status_code=422, detail="No files selected")

    result = await db.execute(
        select(MediaFile, Category)
        .join(ScrapeItem, MediaFile.item_id == ScrapeItem.id)
        .join(Category, MediaFile.category_id == Category.id)
        .filter(ScrapeItem.scrape_id == scrape.id, MediaFile.id.in_(payload.media_ids))
    )
    rows = list(result.all())
    if not rows:
        raise HTTPException(status_code=404, detail="No matching media found")

    pairs = [(m, cat.name) for m, cat in rows]
    return StreamingResponse(
        stream_export(pairs),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{scrape.id}-selection.zip"'},
    )
