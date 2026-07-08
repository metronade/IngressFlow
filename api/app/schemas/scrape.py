from uuid import UUID

from pydantic import BaseModel, Field


class AttestationInput(BaseModel):
    accepted: bool
    text_version: str = Field(min_length=1, max_length=50)


class ScrapeConfig(BaseModel):
    video_only: bool = False
    image_only: bool = False
    include_metadata: bool = False


class ScrapeSubmitRequest(BaseModel):
    raw_text: str = Field(min_length=1)
    config: ScrapeConfig = ScrapeConfig()
    attestation: AttestationInput


class ScrapeSubmitResponse(BaseModel):
    scrape_id: UUID
    share_token: str
    status: str
    links_total: int


class ScrapeItemStatusOut(BaseModel):
    id: UUID
    url: str
    platform: str | None
    status: str
    images_found: int
    images_ok: int
    videos_found: int
    videos_ok: int
    error: str | None


class ScrapeStatusResponse(BaseModel):
    scrape_id: UUID
    status: str
    total_images: int
    total_videos: int
    total_bytes: int
    share_token: str
    items: list[ScrapeItemStatusOut]
