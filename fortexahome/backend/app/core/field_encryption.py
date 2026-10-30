from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _aes() -> AESGCM:
    return AESGCM(get_settings().pii_encryption_bytes)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def encrypt_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    nonce = os.urandom(12)
    ciphertext = _aes().encrypt(nonce, value.encode("utf-8"), field.encode("utf-8"))
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    raw = base64.b64decode(value.encode("ascii"))
    nonce, ciphertext = raw[:12], raw[12:]
    return _aes().decrypt(nonce, ciphertext, field.encode("utf-8")).decode("utf-8")


def _hmac_hex(key: str, value: str) -> str:
    return hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def email_lookup_hash(email: str) -> str:
    return _hmac_hex(get_settings().PII_LOOKUP_KEY, normalize_email(email))


def masked_email(email: str) -> str:
    email = normalize_email(email)
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def license_code_hash(code: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", code.strip().upper())
    return _hmac_hex(get_settings().LICENSE_HMAC_KEY, normalized)


def normalize_license_code(code: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", code.strip().upper())
    if raw.startswith("FH") and len(raw) > 2:
        raw = raw[2:]
    groups = [raw[i : i + 4] for i in range(0, len(raw), 4)]
    return "FH-" + "-".join(groups[:4])


def license_code_last4(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())[-4:]


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def generate_license_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets_choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "FH-" + "-".join(groups)


def secrets_choice(alphabet: str) -> str:
    import secrets

    return secrets.choice(alphabet)
