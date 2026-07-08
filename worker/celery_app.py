import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "ingressflow",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.health", "tasks.batch", "tasks.watchdog", "tasks.retention", "tasks.predictor"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="scrapes",
    # Longer than the longest realistic batch (100 links, worst-case jitter +
    # download time) — deliberately, not a mistake. Redis redelivers an
    # unacked message once this elapses assuming its consumer died; setting
    # it *shorter* than a legitimate run_batch risks two workers processing
    # the same batch at once. tasks.watchdog.requeue_stuck_batches is the
    # actual fast-recovery path for a killed worker (PLAN.md §4.2).
    broker_transport_options={"visibility_timeout": 7200},
    beat_schedule={
        "requeue-stuck-batches": {
            "task": "tasks.watchdog.requeue_stuck_batches",
            "schedule": 60.0,
        },
        "sweep-expired-scrapes": {
            "task": "tasks.retention.sweep_expired",
            "schedule": 60.0,
        },
        "sample-disk": {
            "task": "tasks.predictor.sample_disk",
            "schedule": 3600.0,
        },
    },
)
