"""Disk-layout root and lifecycle helpers shared by the worker (writes,
retention deletes) and the api (reads for gallery/export) — PLAN.md §4.5.

Behind this thin module rather than scattered `os.path` calls so the local
disk backend has one seam to swap for S3/MinIO later, per the `StorageBackend`
interface PLAN.md keeps as a future option (§12) without building it in v1.
"""

import os
import shutil

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/data/scrapes")


def scrape_dir(scrape_id) -> str:
    return os.path.join(MEDIA_ROOT, str(scrape_id))


def delete_scrape_dir(scrape_id) -> None:
    shutil.rmtree(scrape_dir(scrape_id), ignore_errors=True)
