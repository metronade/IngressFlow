"""Sync SQLAlchemy session for Celery tasks.

Celery tasks are plain synchronous callables, so we use psycopg (v3) in sync
mode here rather than pulling asyncio into the worker — the api service is
where the async engine (asyncpg) earns its keep, not here.
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _sync_url() -> str:
    url = os.environ["DATABASE_URL"]
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


engine = create_engine(_sync_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
