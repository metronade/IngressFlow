FROM python:3.12-slim

WORKDIR /app

COPY worker/requirements.txt worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

COPY shared/ shared/
COPY worker/ worker/

ENV PYTHONPATH=/app
WORKDIR /app/worker

CMD ["celery", "-A", "celery_app", "worker", "--concurrency=10", "-Q", "scrapes", "--loglevel=info"]
