"""fastapi-users wiring (PLAN.md §9 Phase 4). User is a plain member of our
own Base/UUIDPk/TimestampMixin hierarchy (shared/models/user.py) rather than
inheriting fastapi-users' base table — verified against fastapi-users 15.0.5
that its SQLAlchemyUserDatabase only needs matching attribute names, not a
particular base class.

No SMTP in v1: verification/reset tokens are logged, not emailed — the same
"wired but not fully live" pattern as Tier-1 platform APIs (§12). Wiring a
real mailer is a Phase F concern, not an architecture change.
"""

import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from shared.models import User
from shared.models.enums import UserRole

logger = logging.getLogger(__name__)

JWT_LIFETIME_SECONDS = 60 * 60 * 24 * 7  # 7 days — no refresh-token flow in v1, so kept long-lived


async def get_user_db(session: AsyncSession = Depends(get_db)) -> AsyncGenerator:
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = get_settings().secret_key
    verification_token_secret = get_settings().secret_key

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        logger.info("user registered: %s", user.email)

        # Bootstrap the first admin account from config — there's no admin UI
        # yet to promote someone, and promoting-via-admin-panel is a
        # chicken-and-egg problem for whoever gets there first (PLAN.md §9
        # Phase 5). Matching this email on registration is the one-time seed;
        # anyone promoted after that goes through the admin panel itself.
        bootstrap_email = get_settings().admin_bootstrap_email
        if bootstrap_email and user.email.lower() == bootstrap_email.lower():
            await self.user_db.update(user, {"is_superuser": True, "role": UserRole.ADMIN})
            logger.warning("bootstrapped %s as admin via ADMIN_BOOTSTRAP_EMAIL", user.email)

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        logger.warning("password reset requested for %s — token (no mailer wired yet): %s", user.email, token)

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        logger.warning("verification requested for %s — token (no mailer wired yet): %s", user.email, token)


async def get_user_manager(user_db=Depends(get_user_db)) -> AsyncGenerator:
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="api/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=get_settings().secret_key, lifetime_seconds=JWT_LIFETIME_SECONDS)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_active_user_optional = fastapi_users.current_user(active=True, optional=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
