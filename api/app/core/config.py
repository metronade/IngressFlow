from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ingressflow:ingressflow@postgres:5432/ingressflow"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "dev-insecure-secret-change-me"  # JWT signing + reset/verify tokens
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_id: str | None = None  # the recurring "paid tier" Price to check out
    public_web_url: str = "http://localhost:3000"  # for Stripe Checkout success/cancel redirects
    admin_bootstrap_email: str | None = None  # one-time: this email becomes admin on registration
    media_root: str = "/data/scrapes"  # for admin disk-usage reporting (shared.storage.MEDIA_ROOT)
    proxy_stats_url: str = "http://proxy:8888/stats"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
