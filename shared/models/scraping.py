import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPk
from .enums import MediaType, ScrapeItemStatus, ScrapeStatus, SourceMethod


class Scrape(Base, UUIDPk, TimestampMixin):
    __tablename__ = "scrapes"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[ScrapeStatus] = mapped_column(
        Enum(ScrapeStatus, native_enum=False, length=20), default=ScrapeStatus.QUEUED
    )
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Nullable: the retention sweep nulls this out on expiry to invalidate the
    # share link at the DB layer too, defense-in-depth alongside the
    # read-time expires_at gate (PLAN.md §4.5).
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    total_images: Mapped[int] = mapped_column(Integer, default=0)
    total_videos: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    proxy_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ua_used: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="scrapes")
    categories: Mapped[list["Category"]] = relationship(
        back_populates="scrape", cascade="all, delete-orphan"
    )
    items: Mapped[list["ScrapeItem"]] = relationship(
        back_populates="scrape", cascade="all, delete-orphan"
    )
    # Authoritative FK lives on LawfulAttestation.scrape_id (avoids a circular
    # FK pair); this is the read-side of that one-to-one.
    attestation: Mapped["LawfulAttestation | None"] = relationship(
        back_populates="scrape", uselist=False
    )


class Category(Base, UUIDPk):
    __tablename__ = "categories"

    scrape_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrapes.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    order: Mapped[int] = mapped_column(Integer, default=0)

    scrape: Mapped["Scrape"] = relationship(back_populates="categories")
    items: Mapped[list["ScrapeItem"]] = relationship(back_populates="category")


class ScrapeItem(Base, UUIDPk):
    __tablename__ = "scrape_items"

    scrape_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrapes.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id"), index=True
    )
    # UUID primary keys don't sort in submission order — run_batch needs a
    # stable, gapless order to process the chain exactly as pasted.
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    url: Mapped[str] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[ScrapeItemStatus] = mapped_column(
        Enum(ScrapeItemStatus, native_enum=False, length=20), default=ScrapeItemStatus.PENDING
    )
    images_found: Mapped[int] = mapped_column(Integer, default=0)
    images_ok: Mapped[int] = mapped_column(Integer, default=0)
    videos_found: Mapped[int] = mapped_column(Integer, default=0)
    videos_ok: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scrape: Mapped["Scrape"] = relationship(back_populates="items")
    category: Mapped["Category"] = relationship(back_populates="items")
    media_files: Mapped[list["MediaFile"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class MediaFile(Base, UUIDPk):
    __tablename__ = "media_files"

    item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrape_items.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id"), index=True
    )
    type: Mapped[MediaType] = mapped_column(Enum(MediaType, native_enum=False, length=10))
    path: Mapped[str] = mapped_column(Text)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_method: Mapped[SourceMethod] = mapped_column(Enum(SourceMethod, native_enum=False, length=20))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    item: Mapped["ScrapeItem"] = relationship(back_populates="media_files")
