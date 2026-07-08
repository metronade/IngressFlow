from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPk
from .enums import UserRole


class User(Base, UUIDPk, TimestampMixin):
    """Structurally compatible with fastapi-users' SQLAlchemyUserDatabase
    (email, hashed_password, is_active, is_superuser, is_verified) without
    inheriting its base table class — fastapi-users' adapter is generic over
    any model with these attributes, not a strict isinstance check (verified
    against fastapi-users 15.0.5), so this stays a plain member of our own
    Base/UUIDPk/TimestampMixin hierarchy alongside everything else in §5."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), default=UserRole.FREE
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credit_balance: Mapped[int] = mapped_column(Integer, default=0)

    scrapes: Mapped[list["Scrape"]] = relationship(back_populates="user")
