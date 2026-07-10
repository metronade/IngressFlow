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


class ProxyNodeOut(BaseModel):
    id: UUID
    name: str
    priority: int
    enabled: bool
    last_seen_at: datetime | None
    created_at: datetime
    # live, from the gateway's own /stats — None if the gateway couldn't be reached
    connected: bool | None = None
    demoted: bool | None = None
    consecutive_failures: int | None = None
    bytes_relayed: int | None = None


class ProxyNodeCreate(BaseModel):
    name: str
    priority: int = 100


class ProxyNodeUpdate(BaseModel):
    priority: int | None = None
    enabled: bool | None = None


class ProxyNodeCreated(BaseModel):
    node: ProxyNodeOut
    token: str  # shown once — never retrievable again
