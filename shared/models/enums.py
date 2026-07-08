import enum


class UserRole(str, enum.Enum):
    PUBLIC = "public"
    FREE = "free"
    PAID = "paid"
    ADMIN = "admin"


class ScrapeStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class ScrapeItemStatus(str, enum.Enum):
    PENDING = "pending"
    SCRAPING = "scraping"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class MediaType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class SourceMethod(str, enum.Enum):
    API = "api"
    YTDLP = "ytdlp"
    GALLERYDL = "gallerydl"
    PLAYWRIGHT = "playwright"


class CredentialKind(str, enum.Enum):
    API_KEY = "api_key"
    OAUTH_TOKEN = "oauth_token"
    COOKIE = "cookie"
