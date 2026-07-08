"""Tier-2 video extractor: a thin, generic wrapper around yt-dlp.

yt-dlp already ships its own per-site extractor registry covering YouTube,
TikTok, Vimeo, X/Twitter, Facebook, and Reddit video, among many others — so
this wrapper is deliberately platform-agnostic. It hands yt-dlp any URL and
lets yt-dlp's own site detection decide whether it can handle it.
"""

import json
import os

import yt_dlp

from . import ExtractedMedia, ExtractResult, UnsupportedURL

_CURATED_FIELDS = ("title", "uploader", "upload_date", "duration", "view_count", "webpage_url")


def extract(
    url: str,
    *,
    user_agent: str,
    proxy_url: str | None,
    cookie_file: str | None,
    work_dir: str,
    config: dict,
) -> ExtractResult:
    if config.get("image_only"):
        # yt-dlp only ever produces video — nothing useful to do here, let
        # the cascade move straight to gallery-dl.
        raise UnsupportedURL("image_only set — skipping yt-dlp")

    out_dir = os.path.join(work_dir, "ytdlp")
    os.makedirs(out_dir, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "http_headers": {"User-Agent": user_agent},
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "writeinfojson": True,
        "socket_timeout": 30,
        # yt-dlp's generic extractor claims *any* http(s) URL as "supported"
        # and then tries to scrape it as a webpage — which defeats the
        # cascade (gallery-dl/Playwright never get a turn on non-video URLs).
        # Restricting to site-specific extractors makes "no match" a real,
        # detectable signal again.
        "allowed_extractors": ["default", "-generic"],
    }
    if proxy_url:
        ydl_opts["proxy"] = proxy_url
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        if "Unsupported URL" in message or "No suitable extractor" in message:
            raise UnsupportedURL(message) from exc
        raise

    media = []
    for fname in sorted(os.listdir(out_dir)):
        if not fname.endswith(".info.json"):
            continue

        info_path = os.path.join(out_dir, fname)
        with open(info_path) as f:
            info = json.load(f)
        stem = fname[: -len(".info.json")]
        media_path = next(
            (
                os.path.join(out_dir, f)
                for f in os.listdir(out_dir)
                if f.startswith(stem) and not f.endswith(".info.json")
            ),
            None,
        )
        os.remove(info_path)
        if media_path is None:
            continue

        extra = {k: info[k] for k in _CURATED_FIELDS if info.get(k) is not None}
        media.append(
            ExtractedMedia(
                path=media_path,
                type="video",
                width=info.get("width"),
                height=info.get("height"),
                duration=info.get("duration"),
                title=info.get("title"),
                extra=extra,
            )
        )

    return ExtractResult(source_method="ytdlp", media=media)
