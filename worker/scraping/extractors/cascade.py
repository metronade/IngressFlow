"""Tier-2 cascade: yt-dlp -> gallery-dl -> Playwright, first success wins
(PLAN.md §4.3). Each tool raises UnsupportedURL when it simply isn't the
right fit for a URL, letting the cascade move to the next one; any other
exception is a genuine failure and propagates to the caller.
"""

from . import ExtractResult, UnsupportedURL, gallerydl, playwright_extractor, ytdlp

_CASCADE = (ytdlp, gallerydl)


def run_tier2(
    url: str,
    *,
    user_agent: str,
    proxy_url: str | None,
    cookie_file: str | None,
    work_dir: str,
    config: dict,
) -> ExtractResult:
    for extractor in _CASCADE:
        try:
            return extractor.extract(
                url,
                user_agent=user_agent,
                proxy_url=proxy_url,
                cookie_file=cookie_file,
                work_dir=work_dir,
                config=config,
            )
        except UnsupportedURL:
            continue

    # Neither tool recognized the site — Playwright's generic DOM scrape is
    # the last resort. It never raises UnsupportedURL: it always "handles"
    # the URL, it just may find nothing.
    return playwright_extractor.extract(
        url,
        user_agent=user_agent,
        proxy_url=proxy_url,
        cookie_file=cookie_file,
        work_dir=work_dir,
        config=config,
    )
