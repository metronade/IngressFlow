"""Streamed ZIP export (PLAN.md §4.5): reads each file in chunks as the ZIP
is generated rather than buffering whole files or the whole archive in
memory — the point of the disk layout mirroring the ZIP structure."""

import os
from collections.abc import Iterable
from datetime import datetime, timezone

from stream_zip import ZIP_AUTO, stream_zip

from shared.models import MediaFile


def _read_chunks(path: str, chunk_size: int = 1 << 20) -> Iterable[bytes]:
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk


def _zip_members(media_files: list[tuple[MediaFile, str]]):
    now = datetime.now(timezone.utc)
    for media, category_name in media_files:
        basename = os.path.basename(media.path)
        yield f"{category_name}/{basename}", now, 0o644, ZIP_AUTO(media.bytes), _read_chunks(media.path)

        sidecar = f"{media.path}.json"
        if os.path.exists(sidecar):
            size = os.path.getsize(sidecar)
            yield f"{category_name}/{basename}.json", now, 0o644, ZIP_AUTO(size), _read_chunks(sidecar)


def stream_export(media_files: list[tuple[MediaFile, str]]) -> Iterable[bytes]:
    """media_files: (MediaFile, category_name) pairs, already scope-filtered
    by the caller (ALL / one category / one item / an explicit id list)."""
    return stream_zip(_zip_members(media_files))
