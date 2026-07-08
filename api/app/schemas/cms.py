from datetime import datetime

from pydantic import BaseModel


class CmsPageOut(BaseModel):
    slug: str
    content_md: str
    updated_at: datetime


class CmsPageUpsert(BaseModel):
    content_md: str
