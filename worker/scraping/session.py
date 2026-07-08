"""Per-batch identity: one UA + one sticky proxy exit for the whole batch,
plus on-demand cookie lookup for a given platform (PLAN.md §4.2, §4.8).
"""

import os
import random
import uuid

from sqlalchemy.orm import Session

from shared.crypto import decrypt_secret
from shared.models import PlatformCredential, Setting
from shared.models.enums import CredentialKind

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]


class BatchSession:
    """One identity held for the whole batch: same UA and, on the Tier-2
    path, the same sticky proxy exit for every link in the sequential chain
    (PLAN.md §4.2's session-affinity rationale)."""

    def __init__(self, scrape_id: str, db: Session):
        self.user_agent = random.choice(_USER_AGENTS)
        gateway = os.environ.get("PROXY_GATEWAY_URL")
        # Admin kill-switch (PLAN.md §9 Phase 5 — Setting `proxy_enabled`,
        # default on). Off means every Tier-2 request this batch makes goes
        # direct through the host's own IP instead of the gateway.
        proxy_enabled = db.query(Setting.value).filter(Setting.key == "proxy_enabled").scalar()
        # Sticky session: the gateway pins one exit per session id for the
        # batch's lifetime (§4.8), encoded as the proxy username the way
        # real rotating-proxy providers do it.
        self.proxy_url: str | None = (
            f"http://session-{scrape_id}:@{gateway.split('://', 1)[1]}"
            if gateway and proxy_enabled is not False
            else None
        )


def cookie_file_for(db: Session, platform: str) -> str | None:
    """Writes a Netscape-format cookie file for `platform` if the admin has
    deposited one; returns its path, or None if none is configured/enabled."""
    cred = (
        db.query(PlatformCredential)
        .filter(
            PlatformCredential.platform == platform,
            PlatformCredential.kind == CredentialKind.COOKIE,
            PlatformCredential.enabled.is_(True),
        )
        .first()
    )
    if cred is None:
        return None

    content = decrypt_secret(cred.secret_blob)
    path = f"/tmp/ingressflow-cookies-{platform}-{uuid.uuid4().hex}.txt"
    with open(path, "w") as f:
        f.write(content)
    return path
