"""CMS for the legal pages (PLAN.md §9 Phase 5 — Impressum/ToS/Privacy).
Public read (any slug an admin has created), admin-only write. Slugs are an
open list — not the fixed impressum/tos/privacy three the model comment
originally sketched — so an operator can add more legal pages later without
a schema change.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.users import current_superuser
from app.db.session import get_db
from app.schemas.cms import CmsPageOut, CmsPageUpsert
from shared.models import CmsPage, User

router = APIRouter(tags=["cms"])


@router.get("/cms/{slug}", response_model=CmsPageOut)
async def get_cms_page(slug: str, db: AsyncSession = Depends(get_db)) -> CmsPageOut:
    page = await db.get(CmsPage, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="No such page")
    return CmsPageOut(slug=page.slug, content_md=page.content_md, updated_at=page.updated_at)


@router.get("/admin/cms", response_model=list[CmsPageOut], dependencies=[Depends(current_superuser)])
async def list_cms_pages(db: AsyncSession = Depends(get_db)) -> list[CmsPageOut]:
    result = await db.execute(select(CmsPage).order_by(CmsPage.slug))
    return [
        CmsPageOut(slug=p.slug, content_md=p.content_md, updated_at=p.updated_at)
        for p in result.scalars().all()
    ]


@router.put("/admin/cms/{slug}", response_model=CmsPageOut)
async def upsert_cms_page(
    slug: str,
    payload: CmsPageUpsert,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(current_superuser),
) -> CmsPageOut:
    page = await db.get(CmsPage, slug)
    now = datetime.now(timezone.utc)
    if page is None:
        page = CmsPage(slug=slug, content_md=payload.content_md, updated_at=now, updated_by=admin.id)
        db.add(page)
    else:
        page.content_md = payload.content_md
        page.updated_at = now
        page.updated_by = admin.id
    await db.commit()
    return CmsPageOut(slug=page.slug, content_md=page.content_md, updated_at=page.updated_at)
