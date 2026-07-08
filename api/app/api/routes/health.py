from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))

    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.ping()
    finally:
        await redis.aclose()

    return {"status": "ok", "db": "ok", "redis": "ok"}
