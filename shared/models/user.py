from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPk
from .enums import UserRole


class User(Base, UUIDPk, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), default=UserRole.FREE
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credit_balance: Mapped[int] = mapped_column(Integer, default=0)

    scrapes: Mapped[list["Scrape"]] = relationship(back_populates="user")
