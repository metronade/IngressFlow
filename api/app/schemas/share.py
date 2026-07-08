from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ShareItemOut(BaseModel):
    id: UUID
    url: str
    platform: str | None
    status: str
    images_found: int
    images_ok: int
    videos_found: int
    videos_ok: int
    error: str | None


class ShareStatusResponse(BaseModel):
    scrape_id: UUID
    status: str
    total_images: int
    total_videos: int
    total_bytes: int
    expires_at: datetime
    items: list[ShareItemOut]


class CategoryOut(BaseModel):
    id: UUID
    name: str
    order: int


class MediaFileOut(BaseModel):
    id: UUID
    item_id: UUID
    category_id: UUID
    category_name: str
    type: str
    bytes: int
    width: int | None
    height: int | None
    duration: float | None
    source_url: str
    source_method: str


class ExportSelectionRequest(BaseModel):
    media_ids: list[UUID]
