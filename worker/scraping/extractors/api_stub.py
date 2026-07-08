"""Tier-1 official-platform-API extraction point (PLAN.md §4.3, §12).

Deliberately not a real client yet: v1 ships scrape-only, and `resolver.route`
only ever returns tier="api" when an admin has added an *enabled*
PlatformCredential for that platform, which is never true out of the box.
This function exists so the dispatch path in tasks/batch.py is real and
already wired — activating a platform later means adding a per-platform
client here (YouTube Data API, Vimeo API, Meta Graph API, …) and flipping the
credential on in admin, not touching the batch task.
"""

from . import PlatformAPINotConfigured


def extract(url: str, *, platform: str, config: dict) -> None:
    raise PlatformAPINotConfigured(
        f"Tier-1 API extraction for '{platform}' is not implemented yet — this should be unreachable "
        "in v1 since resolver.route() only returns tier='api' when a credential is enabled."
    )
