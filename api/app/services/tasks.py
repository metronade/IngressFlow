"""Bridges the API to the worker: enqueueing a batch and requesting a
cooperative cancel (PLAN.md §4.2). The api process never imports worker
code — it only needs to agree on the Celery task name and the Redis key
convention the worker's run_batch checks."""

from celery import Celery
from redis.asyncio import Redis

from app.core.config import get_settings

_celery_client = Celery("ingressflow-api", broker=get_settings().redis_url)


def enqueue_run_batch(scrape_id: str) -> None:
    _celery_client.send_task("tasks.batch.run_batch", args=[scrape_id], queue="scrapes")


async def request_cancel(scrape_id: str) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.set(f"scrape:{scrape_id}:cancelled", "1", ex=86400)
    finally:
        await redis.aclose()
