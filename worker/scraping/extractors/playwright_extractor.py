"""Tier-2 generic fallback: render the page with Playwright and collect
whatever visible <img>/<video> media it finds. Used only when neither
yt-dlp nor gallery-dl recognizes the URL (PLAN.md §4.3) — also the vehicle
for admin cookie injection since it drives a real browser context.
"""

import hashlib
import os

import requests
from playwright.sync_api import sync_playwright

from . import ExtractedMedia, ExtractResult

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}
_KNOWN_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".mov")
_VIDEO_EXTS = (".mp4", ".webm", ".mov")


def _guess_ext(url: str, content_type: str) -> str:
    bare = url.lower().split("?")[0]
    for ext in _KNOWN_EXTS:
        if bare.endswith(ext):
            return ext
    return _EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip(), ".bin")


def _load_netscape_cookies(path: str) -> list[dict]:
    cookies = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 7:
                continue
            domain, _flag, cpath, secure, expires, name, value = parts
            cookies.append(
                {
                    "domain": domain,
                    "path": cpath,
                    "name": name,
                    "value": value,
                    "secure": secure.upper() == "TRUE",
                    "expires": int(expires) if expires.isdigit() else -1,
                }
            )
    return cookies


def extract(
    url: str,
    *,
    user_agent: str,
    proxy_url: str | None,
    cookie_file: str | None,
    work_dir: str,
    config: dict,
) -> ExtractResult:
    out_dir = os.path.join(work_dir, "playwright")
    os.makedirs(out_dir, exist_ok=True)

    launch_kwargs = {}
    if proxy_url:
        launch_kwargs["proxy"] = {"server": proxy_url}

    media_urls: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(user_agent=user_agent)
            if cookie_file:
                context.add_cookies(_load_netscape_cookies(cookie_file))
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30_000)

            if not config.get("video_only"):
                media_urls.update(page.eval_on_selector_all("img", "els => els.map(e => e.currentSrc || e.src)"))
            if not config.get("image_only"):
                media_urls.update(
                    page.eval_on_selector_all("video", "els => els.map(e => e.currentSrc || e.src)")
                )
                media_urls.update(page.eval_on_selector_all("video source", "els => els.map(e => e.src)"))
        finally:
            browser.close()

    http = requests.Session()
    http.headers["User-Agent"] = user_agent
    if proxy_url:
        http.proxies = {"http": proxy_url, "https": proxy_url}

    media = []
    for media_url in filter(None, media_urls):
        try:
            resp = http.get(media_url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException:
            continue

        ext = _guess_ext(media_url, resp.headers.get("Content-Type", ""))
        media_type = "video" if ext in _VIDEO_EXTS else "image"
        fname = f"{hashlib.sha1(media_url.encode()).hexdigest()[:16]}{ext}"
        path = os.path.join(out_dir, fname)
        with open(path, "wb") as f:
            f.write(resp.content)
        media.append(ExtractedMedia(path=path, type=media_type, extra={"source_url": media_url}))

    return ExtractResult(source_method="playwright", media=media)
