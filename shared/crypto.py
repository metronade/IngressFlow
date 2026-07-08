"""Encrypt/decrypt PlatformCredential.secret_blob at rest (PLAN.md §10).

Used by the worker (decrypting a cookie/OAuth token to build a Tier-2
session) and, from Phase E onward, by the admin credential UI (encrypting a
newly-added API key/cookie before it's stored).
"""

import os

from cryptography.fernet import Fernet, InvalidToken


class CredentialEncryptionError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise CredentialEncryptionError(
            "CREDENTIAL_ENCRYPTION_KEY is not set — cannot encrypt/decrypt PlatformCredential secrets"
        )
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise CredentialEncryptionError("could not decrypt secret_blob — wrong key or corrupted data") from exc
