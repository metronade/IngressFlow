"""Admin-only endpoints (PLAN.md §9 Phase 5), all gated by current_superuser.

Settings/credentials here are the actual activation switches the rest of
the system was built to wait for: a Setting row can now override a tier
limit or retention_hours without a redeploy, and an *enabled*
PlatformCredential is the one thing standing between Tier-1 APIs being
"built but inactive" and actually routing there (PLAN.md §4.3/§12).
"""

import shutil
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import psutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.users import current_superuser
from app.db.session import get_db
from app.schemas.admin import (
    AuditLogOut,
    CredentialCreate,
    CredentialOut,
    CredentialUpdate,
    DiskSampleOut,
    PlatformHealthOut,
    SettingOut,
    SettingUpsert,
    SystemStatsOut,
)
from app.services.settings import delete_setting, list_settings, set_setting
from shared.crypto import encrypt_secret
from shared.models import AuditLog, DiskSample, MediaFile, PlatformCredential, ScrapeItem, User
from shared.models.enums import CredentialKind
from shared.storage import MEDIA_ROOT

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(current_superuser)])


# -- settings --------------------------------------------------------------


@router.get("/settings", response_model=list[SettingOut])
async def get_settings_list(db: AsyncSession = Depends(get_db)) -> list[SettingOut]:
    rows = await list_settings(db)
    return [SettingOut(key=r.key, value=r.value) for r in rows]


@router.put("/settings/{key}", response_model=SettingOut)
async def upsert_setting(key: str, payload: SettingUpsert, db: AsyncSession = Depends(get_db)) -> SettingOut:
    row = await set_setting(db, key, payload.value)
    await db.commit()
    return SettingOut(key=row.key, value=row.value)


@router.delete("/settings/{key}", status_code=204)
async def remove_setting(key: str, db: AsyncSession = Depends(get_db)) -> None:
    found = await delete_setting(db, key)
    if not found:
        raise HTTPException(status_code=404, detail="No override set for this key")
    await db.commit()


# -- platform credentials ---------------------------------------------------


@router.get("/credentials", response_model=list[CredentialOut])
async def list_credentials(db: AsyncSession = Depends(get_db)) -> list[CredentialOut]:
    result = await db.execute(select(PlatformCredential).order_by(PlatformCredential.platform))
    return [
        CredentialOut(
            id=c.id,
            platform=c.platform,
            kind=c.kind.value,
            enabled=c.enabled,
            valid_until=c.valid_until,
            created_at=c.created_at,
        )
        for c in result.scalars().all()
    ]


@router.post("/credentials", response_model=CredentialOut, status_code=201)
async def create_credential(
    payload: CredentialCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(current_superuser)
) -> CredentialOut:
    try:
        kind = CredentialKind(payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid kind: {payload.kind}") from exc

    cred = PlatformCredential(
        platform=payload.platform,
        kind=kind,
        secret_blob=encrypt_secret(payload.secret),
        enabled=payload.enabled,
        valid_until=payload.valid_until,
        added_by=admin.id,
    )
    db.add(cred)
    await db.commit()
    return CredentialOut(
        id=cred.id,
        platform=cred.platform,
        kind=cred.kind.value,
        enabled=cred.enabled,
        valid_until=cred.valid_until,
        created_at=cred.created_at,
    )


@router.patch("/credentials/{credential_id}", response_model=CredentialOut)
async def update_credential(
    credential_id: UUID, payload: CredentialUpdate, db: AsyncSession = Depends(get_db)
) -> CredentialOut:
    cred = await db.get(PlatformCredential, credential_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    if payload.enabled is not None:
        cred.enabled = payload.enabled
    if payload.valid_until is not None:
        cred.valid_until = payload.valid_until
    await db.commit()
    return CredentialOut(
        id=cred.id,
        platform=cred.platform,
        kind=cred.kind.value,
        enabled=cred.enabled,
        valid_until=cred.valid_until,
        created_at=cred.created_at,
    )


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    cred = await db.get(PlatformCredential, credential_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.delete(cred)
    await db.commit()


# -- disk-full predictor -----------------------------------------------------


@router.get("/disk", response_model=list[DiskSampleOut])
async def get_disk_samples(hours: int = 48, db: AsyncSession = Depends(get_db)) -> list[DiskSampleOut]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(DiskSample).filter(DiskSample.ts >= since).order_by(DiskSample.ts)
    )
    return [
        DiskSampleOut(
            ts=s.ts,
            free_bytes=s.free_bytes,
            bytes_in_rate=s.bytes_in_rate,
            bytes_out_rate=s.bytes_out_rate,
            hours_to_full=s.hours_to_full,
        )
        for s in result.scalars().all()
    ]


# -- audit log ---------------------------------------------------------------


@router.get("/audit", response_model=list[AuditLogOut])
async def get_audit_log(
    action: str | None = None,
    actor_ip: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogOut]:
    query = select(AuditLog).order_by(AuditLog.ts.desc())
    if action:
        query = query.filter(AuditLog.action == action)
    if actor_ip:
        query = query.filter(AuditLog.actor_ip == actor_ip)
    query = query.offset(offset).limit(min(limit, 500))

    result = await db.execute(query)
    return [
        AuditLogOut(
            id=a.id,
            ts=a.ts,
            actor_user_id=a.actor_user_id,
            actor_ip=a.actor_ip,
            action=a.action,
            target_type=a.target_type,
            target_id=a.target_id,
            detail=a.detail,
        )
        for a in result.scalars().all()
    ]


# -- per-platform health (API-vs-fallback mix) -------------------------------


@router.get("/platform-health", response_model=list[PlatformHealthOut])
async def get_platform_health(db: AsyncSession = Depends(get_db)) -> list[PlatformHealthOut]:
    item_result = await db.execute(
        select(ScrapeItem.platform, ScrapeItem.status, func.count())
        .group_by(ScrapeItem.platform, ScrapeItem.status)
    )
    media_result = await db.execute(
        select(ScrapeItem.platform, MediaFile.source_method, func.count())
        .join(MediaFile, MediaFile.item_id == ScrapeItem.id)
        .group_by(ScrapeItem.platform, MediaFile.source_method)
    )

    platforms: dict[str, dict] = {}

    def entry(platform: str | None) -> dict:
        key = platform or "unknown"
        return platforms.setdefault(
            key,
            {"total": 0, "success": 0, "partial": 0, "failed": 0, "pending": 0, "methods": {}},
        )

    for platform, status, count in item_result.all():
        e = entry(platform)
        e["total"] += count
        e[status.value if status.value in ("success", "partial", "failed") else "pending"] += count

    for platform, method, count in media_result.all():
        e = entry(platform)
        e["methods"][method.value] = e["methods"].get(method.value, 0) + count

    return [
        PlatformHealthOut(
            platform=p,
            total_items=v["total"],
            success=v["success"],
            partial=v["partial"],
            failed=v["failed"],
            pending_or_scraping=v["pending"],
            source_method_counts=v["methods"],
        )
        for p, v in sorted(platforms.items())
    ]


# -- system metrics + proxy stats --------------------------------------------


@router.get("/system", response_model=SystemStatsOut)
async def get_system_stats() -> SystemStatsOut:
    disk = shutil.disk_usage(MEDIA_ROOT)
    return SystemStatsOut(
        cpu_percent=psutil.cpu_percent(interval=0.1),
        memory_percent=psutil.virtual_memory().percent,
        disk_total=disk.total,
        disk_used=disk.used,
        disk_free=disk.free,
    )


@router.get("/proxy-stats")
async def get_proxy_stats() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(get_settings().proxy_stats_url)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach the proxy gateway: {exc}") from exc
