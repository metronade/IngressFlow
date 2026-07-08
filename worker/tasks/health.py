from celery_app import celery_app


@celery_app.task(name="tasks.health.ping")
def ping() -> str:
    return "pong"
