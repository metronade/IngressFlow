from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.scrapes import router as scrapes_router
from app.api.routes.share import router as share_router
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
app.include_router(ws_health_router)
app.include_router(ws_share_router)
