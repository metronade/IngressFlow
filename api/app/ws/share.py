"""WebSocket hub: forwards a scrape's Redis Pub/Sub progress/done events to
the browser (PLAN.md §4.4). Workers never hold WebSocket connections — they
only publish; this process is the only thing that subscribes, which is why
multiple tabs (or a reconnecting client) can all watch the same scrape."""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from shared.models import Scrape, ScrapeItem
from shared.models.enums import ScrapeItemStatus, ScrapeStatus

router = APIRouter()

_TERMINAL = (ScrapeItemStatus.SUCCESS, ScrapeItemStatus.PARTIAL, ScrapeItemStatus.FAILED)


async def _snapshot(db, scrape: Scrape) -> dict:
    total = await db.scalar(
        select(func.count()).select_from(ScrapeItem).filter(ScrapeItem.scrape_id == scrape.id)
    )
    done = await db.scalar(
        select(func.count())
        .select_from(ScrapeItem)
        .filter(ScrapeItem.scrape_id == scrape.id, ScrapeItem.status.in_(_TERMINAL))
    )
    return {
        "scrape_id": str(scrape.id),
        "status": scrape.status.value,
        "links_done": done,
        "links_total": total,
        "total_images": scrape.total_images,
        "total_videos": scrape.total_videos,
        "total_bytes": scrape.total_bytes,
    }


def _is_expired(scrape: Scrape | None) -> bool:
    return (
        scrape is None
        or scrape.status == ScrapeStatus.EXPIRED
        or scrape.expires_at < datetime.now(timezone.utc)
    )


@router.websocket("/ws/share/{token}")
async def ws_share(websocket: WebSocket, token: str) -> None:
    await websocket.accept()

    async with SessionLocal() as db:
        result = await db.execute(select(Scrape).filter(Scrape.share_token == token))
        scrape = result.scalar_one_or_none()

        if _is_expired(scrape):
            await websocket.send_json({"type": "error", "detail": "expired_or_not_found"})
            await websocket.close(code=4410)  # app-level "Gone", mirroring the HTTP 410 gate
            return

        await websocket.send_json({"type": "progress", "data": await _snapshot(db, scrape)})

    redis = Redis.from_url(get_settings().redis_url)
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"scrape:{scrape.id}:progress", f"scrape:{scrape.id}:done")

    async def forward_redis() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            channel = message["channel"]
            channel = channel.decode() if isinstance(channel, bytes) else channel
            if channel.endswith(":done"):
                await websocket.send_json({"type": "done"})
                continue
            data = message["data"]
            data = data.decode() if isinstance(data, bytes) else data
            await websocket.send_json({"type": "progress", "data": json.loads(data)})

    async def watch_disconnect() -> None:
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    forward_task = asyncio.create_task(forward_redis())
    disconnect_task = asyncio.create_task(watch_disconnect())
    try:
        await asyncio.wait([forward_task, disconnect_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        forward_task.cancel()
        disconnect_task.cancel()
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await redis.aclose()
