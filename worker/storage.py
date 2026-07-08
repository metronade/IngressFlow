"""Disk layout, checksums, and dedup for downloaded media (PLAN.md §4.5).

Final layout: /data/scrapes/{scrape_id}/{category}/{filename} — this already
matches the ZIP export structure Phase C will walk directly, so dedup here
must not introduce a layout that needs reorganizing later. A duplicate asset
(same content hash, reposted across links in the batch) gets hard-linked
into its own category folder instead of copied — same bytes on disk, but
still physically present at the path each category expects.
"""

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared.models import MediaFile, ScrapeItem
from shared.models.enums import MediaType, SourceMethod
from worker.scraping.extractors import ExtractedMedia

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/data/scrapes")

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_category_name(name: str) -> str:
    """User-supplied category header text becomes a folder name — strip
    anything that could path-traverse or collide with reserved names."""
    safe = _UNSAFE.sub("_", name.strip()).strip("._") or "uncategorized"
    return safe[:100]


def category_dir(scrape_id: str, category_name: str) -> str:
    path = os.path.join(MEDIA_ROOT, str(scrape_id), sanitize_category_name(category_name))
    os.makedirs(path, exist_ok=True)
    return path


def checksum_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_duplicate(db: Session, scrape_id: str, checksum: str) -> MediaFile | None:
    return (
        db.query(MediaFile)
        .join(ScrapeItem, MediaFile.item_id == ScrapeItem.id)
        .filter(ScrapeItem.scrape_id == scrape_id, MediaFile.checksum == checksum)
        .first()
    )


def persist_media(
    db: Session,
    *,
    scrape_id: str,
    item_id: str,
    category_id: str,
    category_name: str,
    extracted: ExtractedMedia,
    source_method: str,
    source_url: str,
    include_metadata: bool,
) -> MediaFile:
    checksum = checksum_of(extracted.path)
    duplicate = _find_duplicate(db, scrape_id, checksum)

    dest_dir = category_dir(scrape_id, category_name)
    ext = os.path.splitext(extracted.path)[1]
    dest_path = os.path.join(dest_dir, f"{uuid.uuid4().hex}{ext}")

    if duplicate is not None:
        try:
            os.link(duplicate.path, dest_path)
        except OSError:
            shutil.copy2(duplicate.path, dest_path)
        os.remove(extracted.path)
    else:
        shutil.move(extracted.path, dest_path)

    metadata = dict(extracted.extra)
    metadata.update(
        {
            "source_url": source_url,
            "source_method": source_method,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if include_metadata:
        with open(f"{dest_path}.json", "w") as f:
            json.dump(metadata, f, indent=2, default=str)

    media_file = MediaFile(
        item_id=item_id,
        category_id=category_id,
        type=MediaType(extracted.type),
        path=dest_path,
        bytes=os.path.getsize(dest_path),
        width=extracted.width,
        height=extracted.height,
        duration=extracted.duration,
        source_url=source_url,
        source_method=SourceMethod(source_method),
        checksum=checksum,
        metadata_json=metadata,
    )
    db.add(media_file)
    return media_file
