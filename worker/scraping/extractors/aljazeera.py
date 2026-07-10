"""Tier-2 extractor for Al Jazeera video pages.

yt-dlp ships its own AlJazeeraIE, but its _VALID_URL regex only covers
/videos/<date>/<slug> (plural), /programs/<name>/<date>/<slug>, /features/,
and /news/ — not the /video/<program>/<date>/<slug> shape (singular "video"
plus a program-name segment) Al Jazeera actually uses for program episodes
like Inside Story. That URL falls through to the generic Tier-2 cascade and
ends at Playwright's DOM scrape, which only picks up <img> tags — no video.

Turns out no browser interaction is needed at all: the video's Brightcove
embed URL is already present in the page's own server-rendered JSON-LD
(schema.org VideoObject.embedUrl). This fetches the page, pulls that embed
URL out, and hands it straight to the existing yt-dlp wrapper — which
already extracts Brightcove (players.brightcove.net) perfectly on its own.
"""

import json
import re
from urllib.parse import urlparse

import requests

from . import ExtractResult, UnsupportedURL
from . import ytdlp

_DOMAIN_RE = re.compile(r"(^|\.)aljazeera\.(com|net)$")
_JSONLD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL)


def _is_aljazeera(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return bool(_DOMAIN_RE.search(host))


def _find_brightcove_embed_url(html: str) -> str | None:
    for block in _JSONLD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for candidate in data if isinstance(data, list) else [data]:
            if not isinstance(candidate, dict):
                continue
            embed_url = candidate.get("embedUrl")
            if embed_url and "brightcove.net" in embed_url:
                return embed_url
    return None


def extract(
    url: str,
    *,
    user_agent: str,
    proxy_url: str | None,
    cookie_file: str | None,
    work_dir: str,
    config: dict,
) -> ExtractResult:
    if not _is_aljazeera(url):
        raise UnsupportedURL("not an aljazeera.com/net URL")

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, proxies=proxies, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UnsupportedURL(f"could not fetch Al Jazeera page: {exc}") from exc

    embed_url = _find_brightcove_embed_url(resp.text)
    if embed_url is None:
        # A text/image-only article, or a page shape this hasn't seen
        # before — let the cascade fall through to gallery-dl/Playwright so
        # any images on the page still get picked up.
        raise UnsupportedURL("no Brightcove embed found on this Al Jazeera page")

    return ytdlp.extract(
        embed_url,
        user_agent=user_agent,
        proxy_url=proxy_url,
        cookie_file=cookie_file,
        work_dir=work_dir,
        config=config,
    )
