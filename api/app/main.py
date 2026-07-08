from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.billing import router as billing_router
from app.api.routes.health import router as health_router
from app.api.routes.scrapes import router as scrapes_router
from app.api.routes.share import router as share_router
from app.core.users import auth_backend, fastapi_users
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.ws.health import router as ws_health_router
from app.ws.share import router as ws_share_router

app = FastAPI(title="IngressFlow API")

# Permissive for local dev (web:3000 -> api:8000 without NPM in front). NPM does
# path-based routing in prod, so real deployments won't need cross-origin calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(scrapes_router, prefix="/api")
app.include_router(share_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(ws_health_router)
app.include_router(ws_share_router)

# fastapi-users (PLAN.md Phase 4): register/login/verify/reset/profile.
app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/api/auth/jwt", tags=["auth"])
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate), prefix="/api/auth", tags=["auth"]
)
app.include_router(fastapi_users.get_verify_router(UserRead), prefix="/api/auth", tags=["auth"])
app.include_router(fastapi_users.get_reset_password_router(), prefix="/api/auth", tags=["auth"])
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/api/users", tags=["users"])
