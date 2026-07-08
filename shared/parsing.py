"""Category-header text parser for scrape submissions (PLAN.md §1 input format).

Runs at scrape-submission time in the API (it must produce Category/ScrapeItem
rows before a batch exists), not inside the worker's per-link loop — so it
lives here in shared/ rather than under worker/scraping/ as PLAN.md's
directory sketch originally placed it. shared/ is already the single source
of truth for anything both api and worker (or, as here, api alone) needs.
"""

from dataclasses import dataclass, field

UNCATEGORIZED = "uncategorized"


@dataclass
class ParsedCategory:
    name: str
    urls: list[str] = field(default_factory=list)


@dataclass
class ParsedBatch:
    categories: list[ParsedCategory]

    @property
    def total_links(self) -> int:
        return sum(len(c.urls) for c in self.categories)


def _is_url(line: str) -> bool:
    return line.startswith("http://") or line.startswith("https://")


def parse_batch(raw_text: str) -> ParsedBatch:
    """Groups pasted URLs under the category header text above them.

    A header stays "current" across blank lines until a new header line (any
    non-URL, non-blank line) appears — matching the brief's
    "[Empty Line or New Header]" as equivalent boundary signals. URLs that
    appear before any header are bucketed under "uncategorized". A header
    with no URLs under it (e.g. two headers in a row) produces no category.
    Repeated header text merges into the same category, in first-seen order.
    """
    order: list[str] = []
    by_name: dict[str, ParsedCategory] = {}
    current = UNCATEGORIZED

    def bucket(name: str) -> ParsedCategory:
        if name not in by_name:
            by_name[name] = ParsedCategory(name=name)
            order.append(name)
        return by_name[name]

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_url(line):
            bucket(current).urls.append(line)
        else:
            current = line

    categories = [by_name[name] for name in order if by_name[name].urls]
    return ParsedBatch(categories=categories)
