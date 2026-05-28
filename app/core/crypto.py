from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import KnowForgeError


def _fernet_from_secret(secret: str) -> Fernet:
    # Fernet requires 32-byte urlsafe base64 key.
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str, *, secret: str | None) -> str:
    if not secret:
        raise KnowForgeError(
            "Server encryption key not configured.",
            status_code=500,
            code="llm_key_encryption_missing",
        )
    token = _fernet_from_secret(secret).encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str, *, secret: str | None) -> str:
    if not secret:
        raise KnowForgeError(
            "Server encryption key not configured.",
            status_code=500,
            code="llm_key_encryption_missing",
        )
    try:
        value = _fernet_from_secret(secret).decrypt(ciphertext.encode("utf-8"))
        return value.decode("utf-8")
    except InvalidToken as exc:
        raise KnowForgeError(
            "Stored key could not be decrypted. Reconnect your provider key.",
            status_code=500,
            code="llm_key_decrypt_failed",
        ) from exc

