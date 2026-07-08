"""Generic Setting-table read/write helpers (PLAN.md §9 Phase 5 — admin
tuning of limits/retention/proxy without a redeploy). limits.py has its own
inline reader for the `limits.<role>.<field>` namespace; this is the
general-purpose version used for everything else (retention_hours,
proxy_enabled) and by the admin settings API itself.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Setting


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    result = await db.execute(select(Setting.value).filter(Setting.key == key))
    value = result.scalar_one_or_none()
    return value if value is not None else default


async def set_setting(db: AsyncSession, key: str, value: Any) -> Setting:
    existing = await db.get(Setting, key)
    if existing is None:
        existing = Setting(key=key, value=value)
        db.add(existing)
    else:
        existing.value = value
    return existing


async def delete_setting(db: AsyncSession, key: str) -> bool:
    existing = await db.get(Setting, key)
    if existing is None:
        return False
    await db.delete(existing)
    return True


async def list_settings(db: AsyncSession) -> list[Setting]:
    result = await db.execute(select(Setting).order_by(Setting.key))
    return list(result.scalars().all())
