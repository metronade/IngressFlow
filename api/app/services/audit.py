"""Append-only audit trail: who did what, when (PLAN.md §4.7). Every write
goes through here so the shape stays consistent — never update or delete
a row once written."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import AuditLog


def write_audit(
    db: AsyncSession,
    *,
    actor_ip: str,
    action: str,
    target_type: str,
    actor_user_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(entry)
    return entry
