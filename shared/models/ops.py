import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class UsageEvent(Base, TimestampMixin):
    """Billing/limits accounting. proxy_bytes is internal metering only — no provider billing (§4.8)."""

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    ip: Mapped[str] = mapped_column(String(45), index=True)
    scrape_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrapes.id"), nullable=True
    )
    links_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    proxy_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    exit_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)


class Setting(Base):
    """Admin-tunable knobs: max_links, max_scrapes_per_ip_24h, retention_hours, proxy_enabled, …"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)


class CmsPage(Base):
    """Editable Impressum / ToS / Privacy content (open-ended slug — more legal pages may be added)."""

    __tablename__ = "cms_pages"

    slug: Mapped[str] = mapped_column(String(50), primary_key=True)
    content_md: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class DiskSample(Base):
    """Hourly disk-full predictor samples (§4.6)."""

    __tablename__ = "disk_samples"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    free_bytes: Mapped[int] = mapped_column(BigInteger)
    bytes_in_rate: Mapped[float] = mapped_column(Float)
    bytes_out_rate: Mapped[float] = mapped_column(Float)
    hours_to_full: Mapped[float | None] = mapped_column(Float, nullable=True)


class ProxyNode(Base, TimestampMixin):
    """Residential proxy mesh node — a self-registering agent (§4.8a). Durable
    admin config only: token_hash never stores the plaintext (same one-time-
    reveal pattern as PlatformCredential.secret_blob), priority/enabled are
    admin-managed here. Live connection state (currently connected, recent
    failure streak, bytes relayed) stays in the gateway process's memory —
    it's the one thing actually holding the WebSocket connections — and is
    surfaced to the admin UI via the gateway's own status endpoint, not this
    table."""

    __tablename__ = "proxy_nodes"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    token_hash: Mapped[str] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower tried first
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
