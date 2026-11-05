from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from app.core.config import get_settings


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def verification_code_hash(activation_id: uuid.UUID, code: str) -> str:
    key = get_settings().EMAIL_VERIFICATION_HMAC_KEY
    if len(key) < 32:
        raise RuntimeError("EMAIL_VERIFICATION_HMAC_KEY não está configurada")
    message = f"{activation_id}:{code}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_code(activation_id: uuid.UUID, code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(verification_code_hash(activation_id, code), expected_hash)
