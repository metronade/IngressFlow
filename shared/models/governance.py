import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPk
from .enums import CredentialKind


class LawfulAttestation(Base, UUIDPk):
    """The per-scrape rights assertion that transfers responsibility to the operator (PLAN.md §4.7)."""

    __tablename__ = "lawful_attestations"

    scrape_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrapes.id", ondelete="CASCADE"), unique=True, index=True
    )
    text_version: Mapped[str] = mapped_column(String(50))
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    actor_ip: Mapped[str] = mapped_column(String(45))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scrape: Mapped["Scrape"] = relationship(back_populates="attestation")


class AuditLog(Base, UUIDPk):
    """Append-only: who did what, when (PLAN.md §4.7). No app-level update/delete."""

    __tablename__ = "audit_log"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    actor_ip: Mapped[str] = mapped_column(String(45))
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class PlatformCredential(Base, UUIDPk, TimestampMixin):
    """Tier-1 API keys AND Tier-2 OAuth tokens/cookies — encrypted at rest (PLAN.md §10)."""

    __tablename__ = "platform_credentials"

    platform: Mapped[str] = mapped_column(String(50), index=True)
    kind: Mapped[CredentialKind] = mapped_column(Enum(CredentialKind, native_enum=False, length=20))
    secret_blob: Mapped[str] = mapped_column(Text)  # Fernet/KMS-encrypted ciphertext, base64 text
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
