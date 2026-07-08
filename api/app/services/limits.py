"""Tier-based limits (PLAN.md §5/§9 Phase 4): public/free/paid/admin.
Defaults here are hardcoded fallbacks — Phase E's admin UI is what actually
owns tuning these via the `Setting` table (`limits.<role>.<field>`); until
then no Setting rows exist and the fallbacks apply everywhere.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from shared.models import Setting, User
from shared.models.enums import UserRole

# Hard architectural ceiling from PLAN.md §1 — a property of the
# sequential-chain design, not a monetization lever. No tier may exceed it.
ARCHITECTURAL_MAX_LINKS = 100

_DEFAULTS: dict[UserRole, dict[str, int | None]] = {
    UserRole.PUBLIC: {"max_links_per_scrape": 25, "max_scrapes_per_period": 10},
    UserRole.FREE: {"max_links_per_scrape": 50, "max_scrapes_per_period": 20},
    UserRole.PAID: {"max_links_per_scrape": ARCHITECTURAL_MAX_LINKS, "max_scrapes_per_period": None},
    UserRole.ADMIN: {"max_links_per_scrape": ARCHITECTURAL_MAX_LINKS, "max_scrapes_per_period": None},
}


@dataclass
class TierLimits:
    role: UserRole
    max_links_per_scrape: int
    max_scrapes_per_period: int | None  # None = no cap (paid/admin default)


async def _setting_override(db: AsyncSession, role: UserRole, field: str) -> int | None:
    key = f"limits.{role.value}.{field}"
    result = await db.execute(select(Setting.value).filter(Setting.key == key))
    value = result.scalar_one_or_none()
    return int(value) if value is not None else None


async def resolve_limits(db: AsyncSession, user: User | None) -> TierLimits:
    role = user.role if user is not None else UserRole.PUBLIC
    defaults = _DEFAULTS[role]

    max_links = await _setting_override(db, role, "max_links_per_scrape")
    if max_links is None:
        max_links = defaults["max_links_per_scrape"]
    max_links = min(max_links, ARCHITECTURAL_MAX_LINKS)

    max_period = await _setting_override(db, role, "max_scrapes_per_period")
    if max_period is None:
        max_period = defaults["max_scrapes_per_period"]

    return TierLimits(role=role, max_links_per_scrape=max_links, max_scrapes_per_period=max_period)


def _rate_limit_key(user: User | None, ip: str) -> str:
    return f"ratelimit:user:{user.id}:24h" if user is not None else f"ratelimit:ip:{ip}:24h"


async def enforce_rate_limit(user: User | None, ip: str, limits: TierLimits) -> None:
    """Called only for a submission that already passed attestation + link-count
    checks, so a rejected request never burns part of the caller's quota."""
    if limits.max_scrapes_per_period is None:
        return

    redis = Redis.from_url(get_settings().redis_url)
    try:
        key = _rate_limit_key(user, ip)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 86400)
        if count > limits.max_scrapes_per_period:
            scope = "account" if user is not None else "IP address"
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Scrape limit reached for this {scope} "
                    f"({limits.max_scrapes_per_period} per 24h). Try again later or upgrade."
                ),
            )
    finally:
        await redis.aclose()
