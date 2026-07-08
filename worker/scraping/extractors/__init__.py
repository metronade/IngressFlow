"""Common types shared by every Tier-1/Tier-2 extractor (PLAN.md §4.3)."""

from dataclasses import dataclass, field


class UnsupportedURL(Exception):
    """Raised by a tier when it recognizes it simply isn't the right tool for
    this URL, so the cascade should try the next one. Any other exception
    means the right tool tried and failed — that's a real failure, not a
    cascade signal."""


class PlatformAPINotConfigured(Exception):
    """Tier-1 is built but inactive until an admin adds a credential for the
    platform (PLAN.md §12) — this is what a v1 deployment always raises."""


@dataclass
class ExtractedMedia:
    path: str
    type: str  # "image" | "video"
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    title: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ExtractResult:
    source_method: str  # "api" | "ytdlp" | "gallerydl" | "playwright"
    media: list[ExtractedMedia] = field(default_factory=list)
