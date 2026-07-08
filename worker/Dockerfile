FROM python:3.12-slim-bookworm

# ffmpeg: yt-dlp needs it to mux separately-fetched bestvideo+bestaudio streams.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY worker/requirements.txt worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

# Playwright's own system deps (fonts, codecs, etc.) for headless Chromium —
# the Tier-2 generic-fallback extractor (PLAN.md §4.3).
RUN python -m playwright install --with-deps chromium

COPY shared/ shared/
COPY worker/ worker/

ENV PYTHONPATH=/app
WORKDIR /app/worker

CMD ["celery", "-A", "celery_app", "worker", "--concurrency=10", "-Q", "scrapes", "--loglevel=info"]
