from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from app.core.config import Settings
from app.core.field_encryption import decrypt_text, encrypt_text, generate_license_code, license_code_hash
from app.core.rate_limit import client_ip
from app.core.security import generate_token, hash_token


def settings_values(**overrides):
    values = {
        "DATABASE_URL": "postgresql+psycopg://app:pass@localhost:5432/fortexahome_test",
        "MIGRATION_DATABASE_URL": "postgresql+psycopg://owner:pass@localhost:5432/fortexahome_test",
        "SECRET_KEY": "s" * 48,
        "PII_ENCRYPTION_KEY": base64.b64encode(b"a" * 32).decode(),
        "PII_LOOKUP_KEY": "l" * 48,
        "LICENSE_HMAC_KEY": "h" * 48,
        "EMAIL_VERIFICATION_HMAC_KEY": "e" * 48,
        "OUTBOX_DB_PASSWORD": "o" * 48,
        "APP_BASE_URL": "https://app.example.com",
        "PAYMENT_SANDBOX_ENABLED": False,
    }
    values.update(overrides)
    return Settings(**values)


def request(remote: str, **headers: str):
    return SimpleNamespace(client=SimpleNamespace(host=remote), headers=Headers(headers))


def test_encryption_round_trip_and_field_binding():
    ciphertext = encrypt_text("hello", "users.name")
    assert ciphertext and decrypt_text(ciphertext, "users.name") == "hello"
    with pytest.raises(Exception):
        decrypt_text(ciphertext, "users.email")


def test_tokens_are_random_and_hash_is_stable():
    first, second = generate_token(), generate_token()
    assert first != second
    assert hash_token(first) == hash_token(first)
    assert hash_token(first) != first


def test_license_code_shape_and_hash_normalization():
    code = generate_license_code()
    assert code.startswith("FH-")
    assert len(code.split("-")) == 4
    assert license_code_hash(code) == license_code_hash(code.lower().replace("-", ""))


def test_production_requires_resend_and_public_sender_domain():
    common = {
        "ENV": "production",
        "DEBUG": False,
        "SESSION_COOKIE_SECURE": True,
        "DEMO_MODE": False,
        "ALLOW_PUBLIC_SIGNUP": False,
        "CORS_ORIGINS": "https://app.example.com",
    }
    with pytest.raises(ValueError, match="EMAIL_PROVIDER"):
        settings_values(**common, EMAIL_PROVIDER="dev")
    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        settings_values(**common, EMAIL_PROVIDER="resend", EMAIL_FROM="Support <hello@example.com>")
    configured = settings_values(
        **common,
        PAYMENT_PROVIDER="hotmart",
        PAYMENT_WEBHOOK_SECRET="",
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="test-api-key",
        EMAIL_FROM="Support <hello@example.com>",
    )
    assert configured.is_production


def test_production_rejects_sandbox_provider_enabled():
    with pytest.raises(ValueError, match="PAYMENT_SANDBOX_ENABLED"):
        settings_values(
            ENV="production",
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            DEMO_MODE=False,
            ALLOW_PUBLIC_SIGNUP=False,
            CORS_ORIGINS="https://app.example.com",
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-api-key",
            EMAIL_FROM="Fortexa <hello@example.com>",
            PAYMENT_PROVIDER="hotmart",
            PAYMENT_SANDBOX_ENABLED=True,
            PAYMENT_WEBHOOK_SECRET="short",
        )


def test_sandbox_enabled_requires_its_own_secret():
    with pytest.raises(ValueError, match="PAYMENT_WEBHOOK_SECRET"):
        settings_values(
            ENV="test",
            PAYMENT_SANDBOX_ENABLED=True,
            PAYMENT_WEBHOOK_SECRET="short",
        )


def test_production_requires_a_dedicated_email_verification_key():
    with pytest.raises(ValueError, match="EMAIL_VERIFICATION_HMAC_KEY"):
        settings_values(
            ENV="production",
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            DEMO_MODE=False,
            ALLOW_PUBLIC_SIGNUP=False,
            CORS_ORIGINS="https://app.example.com",
            PAYMENT_PROVIDER="hotmart",
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-api-key",
            EMAIL_FROM="Fortexa <hello@example.com>",
            EMAIL_VERIFICATION_HMAC_KEY="h" * 48,
        )


def test_production_requires_separate_outbox_worker_credentials():
    with pytest.raises(ValueError, match="OUTBOX_DB_PASSWORD"):
        settings_values(
            ENV="production",
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            DEMO_MODE=False,
            ALLOW_PUBLIC_SIGNUP=False,
            CORS_ORIGINS="https://app.example.com",
            PAYMENT_PROVIDER="hotmart",
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-api-key",
            EMAIL_FROM="Fortexa <hello@example.com>",
            OUTBOX_DB_PASSWORD="",
        )


def test_hotmart_production_configuration_is_explicit_and_complete():
    common = {
        "ENV": "production",
        "DEBUG": False,
        "SESSION_COOKIE_SECURE": True,
        "DEMO_MODE": False,
        "ALLOW_PUBLIC_SIGNUP": False,
        "CORS_ORIGINS": "https://app.example.com",
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": "test-api-key",
        "EMAIL_FROM": "Fortexa <hello@example.com>",
        "HOTMART_ENABLED": True,
    }
    with pytest.raises(ValueError, match="HOTMART_WEBHOOK_HOTTOK"):
        settings_values(**common)
    configured = settings_values(
        **common,
        # The legacy sandbox HMAC remains unset; Hotmart has its own auth setting.
        PAYMENT_WEBHOOK_SECRET="",
        HOTMART_WEBHOOK_HOTTOK="fictional-test-hottok-value",
        HOTMART_PRODUCT_UCODE="UCODE-FICTICIO",
        HOTMART_PRODUCT_SLUG="fortexahome-approved-product",
    )
    assert configured.HOTMART_ENABLED
