"""URL -> platform, then platform -> (tier, egress) (PLAN.md §4.3, §4.8).

Egress is a hard rule, not a per-request choice: Tier-1 API calls always go
direct (an authenticated call has nothing to hide from and proxying it looks
like account abuse); Tier-2 scrape calls always go through the proxy gateway.
Tier-1 is "built but inactive" in v1 — `route()` only returns tier="api" when
the caller passes a platform that actually has an enabled credential, which
in a fresh deployment is never, since no PlatformCredential rows exist yet.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

_PLATFORM_DOMAINS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "reddit.com": "reddit",
    "redd.it": "reddit",
    "snapchat.com": "snapchat",
    "facebook.com": "facebook",
    "fb.watch": "facebook",
    "vimeo.com": "vimeo",
}


@dataclass(frozen=True)
class Route:
    platform: str
    tier: str  # "api" | "scrape"
    egress: str  # "direct" | "proxy"


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for domain, platform in _PLATFORM_DOMAINS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    return "unknown"


def route(url: str, enabled_api_platforms: set[str]) -> Route:
    platform = detect_platform(url)
    if platform in enabled_api_platforms:
        return Route(platform=platform, tier="api", egress="direct")
    return Route(platform=platform, tier="scrape", egress="proxy")
