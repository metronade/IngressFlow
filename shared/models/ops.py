import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
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
