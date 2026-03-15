from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from tempfile import gettempdir

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


class CredentialStoreError(RuntimeError):
    pass


def _resolve_encryption_key() -> bytes:
    raw = (settings.BROKER_CREDENTIAL_ENCRYPTION_KEY or "").strip()
    if not raw:
        raise CredentialStoreError(
            "BROKER_CREDENTIAL_ENCRYPTION_KEY is required when "
            "multi-account credentials are enabled"
        )
    try:
        decoded = base64.b64decode(raw)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    if len(raw.encode("utf-8")) == 32:
        return raw.encode("utf-8")
    raise CredentialStoreError(
        "BROKER_CREDENTIAL_ENCRYPTION_KEY must be a 32-byte key "
        "or base64-encoded 32-byte value"
    )


def fingerprint_private_key(private_key_pem: str) -> str:
    return hashlib.sha256(private_key_pem.encode("utf-8")).hexdigest()[:32]


def encrypt_private_key(private_key_pem: str) -> str:
    aesgcm = AESGCM(_resolve_encryption_key())
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, private_key_pem.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_private_key(payload: str) -> str:
    aesgcm = AESGCM(_resolve_encryption_key())
    decoded = base64.b64decode(payload.encode("ascii"))
    nonce, ciphertext = decoded[:12], decoded[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def materialize_private_key(account_id: str, private_key_pem: str) -> str:
    safe_account = "".join(ch if ch.isalnum() else "_" for ch in account_id)
    digest = hashlib.sha256(private_key_pem.encode("utf-8")).hexdigest()[:12]
    target = Path(gettempdir()) / f"ai_trading_tiger_{safe_account}_{digest}.pem"
    target.write_text(private_key_pem, encoding="utf-8")
    return str(target)
