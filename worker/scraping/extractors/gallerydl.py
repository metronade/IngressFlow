"""Tier-2 image extractor: a thin, generic wrapper around gallery-dl.

Like yt-dlp for video, gallery-dl ships its own per-site extractor registry
(Instagram, Reddit, X/Twitter, Snapchat, generic direct-image links, …), so
this wrapper hands it any URL and lets gallery-dl's own site detection
decide whether it can handle it.
"""

import os

import gallery_dl.config
import gallery_dl.extractor
import gallery_dl.job

from . import ExtractedMedia, ExtractResult, UnsupportedURL

_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v")


def extract(
    url: str,
    *,
    user_agent: str,
    proxy_url: str | None,
    cookie_file: str | None,
    work_dir: str,
    config: dict,
) -> ExtractResult:
    if config.get("video_only"):
        raise UnsupportedURL("video_only set — skipping gallery-dl")

    if gallery_dl.extractor.find(url) is None:
        raise UnsupportedURL(f"no gallery-dl extractor for {url}")

    out_dir = os.path.join(work_dir, "gallerydl")
    os.makedirs(out_dir, exist_ok=True)

    # gallery-dl's config is process-global; each call resets it. Safe across
    # concurrent batches (separate worker processes under Celery prefork),
    # and each sequential item in this batch resets it before use.
    gallery_dl.config.clear()
    gallery_dl.config.set((), "base-directory", out_dir)
    gallery_dl.config.set((), "directory", [])  # flat output, no per-site subfolders
    gallery_dl.config.set(("extractor",), "user-agent", user_agent)
    if proxy_url:
        gallery_dl.config.set(("extractor",), "proxy", proxy_url)
    if cookie_file:
        gallery_dl.config.set(("extractor",), "cookies", cookie_file)

    gallery_dl.job.DownloadJob(url).run()

    media = []
    for root, _dirs, files in os.walk(out_dir):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            media_type = "video" if ext in _VIDEO_EXTS else "image"
            media.append(ExtractedMedia(path=os.path.join(root, fname), type=media_type))

    return ExtractResult(source_method="gallerydl", media=media)
