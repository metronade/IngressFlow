from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SettingOut(BaseModel):
    key: str
    value: Any


class SettingUpsert(BaseModel):
    value: Any


class CredentialOut(BaseModel):
    id: UUID
    platform: str
    kind: str
    enabled: bool
    valid_until: datetime | None
    created_at: datetime


class CredentialCreate(BaseModel):
    platform: str
    kind: str  # "api_key" | "oauth_token" | "cookie"
    secret: str  # plaintext in the request; encrypted before it touches the DB
    enabled: bool = True
    valid_until: datetime | None = None


class CredentialUpdate(BaseModel):
    enabled: bool | None = None
    valid_until: datetime | None = None


class DiskSampleOut(BaseModel):
    ts: datetime
    free_bytes: int
    bytes_in_rate: float
    bytes_out_rate: float
    hours_to_full: float | None


class AuditLogOut(BaseModel):
    id: UUID
    ts: datetime
    actor_user_id: UUID | None
    actor_ip: str
    action: str
    target_type: str
    target_id: UUID | None
    detail: dict | None


class PlatformHealthOut(BaseModel):
    platform: str
    total_items: int
    success: int
    partial: int
    failed: int
    pending_or_scraping: int
    source_method_counts: dict[str, int]


class SystemStatsOut(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_total: int
    disk_used: int
    disk_free: int
