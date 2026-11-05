from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.core.config import Settings


def _production_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "ENV": "production",
            "DEBUG": "false",
            "LOG_LEVEL": "INFO",
            "SESSION_COOKIE_SECURE": "true",
            "SESSION_COOKIE_SAMESITE": "lax",
            "EMAIL_PROVIDER": "resend",
            "RESEND_API_KEY": "test-resend-key",
            "EMAIL_FROM": "Fortexa <hello@example.com>",
            "APP_BASE_URL": "https://app.example.com",
            "CORS_ORIGINS": "https://app.example.com",
            "PAYMENT_PROVIDER": "hotmart",
            "PAYMENT_SANDBOX_ENABLED": "false",
            "HOTMART_ENABLED": "false",
        }
    )
    return env


def test_production_route_set_does_not_register_hmac_sandbox():
    code = """
from fastapi.testclient import TestClient
from app.main import app
paths = {route.path for route in app.routes}
assert "/api/v1/webhooks/payments/hmac_sandbox" not in paths
assert "/api/v1/webhooks/hotmart" in paths
with TestClient(app) as client:
    response = client.post("/api/v1/webhooks/payments/hmac_sandbox", json={})
    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"
print("OK")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=_production_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout
    assert "test-resend-key" not in completed.stdout + completed.stderr


def test_production_settings_reject_sandbox_route_enablement(monkeypatch):
    with pytest.raises(ValueError, match="PAYMENT_SANDBOX_ENABLED"):
        Settings(
            ENV="production",
            DEBUG=False,
            LOG_LEVEL="INFO",
            DATABASE_URL="postgresql+psycopg://app:pass@localhost:5432/fortexahome_test",
            MIGRATION_DATABASE_URL="postgresql+psycopg://owner:pass@localhost:5432/fortexahome_test",
            APP_DB_USER="app",
            OUTBOX_DB_USER="worker",
            OUTBOX_DB_PASSWORD="worker-password-with-enough-length-000000",
            SECRET_KEY="s" * 48,
            PII_ENCRYPTION_KEY="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
            PII_LOOKUP_KEY="l" * 48,
            LICENSE_HMAC_KEY="h" * 48,
            EMAIL_VERIFICATION_HMAC_KEY="e" * 48,
            RATE_LIMIT_HMAC_KEY="r" * 48,
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test",
            EMAIL_FROM="Fortexa <hello@example.com>",
            APP_BASE_URL="https://app.example.com",
            CORS_ORIGINS="https://app.example.com",
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_SAMESITE="lax",
            PAYMENT_PROVIDER="hotmart",
            PAYMENT_SANDBOX_ENABLED=True,
            PAYMENT_WEBHOOK_SECRET="test-webhook-secret-not-for-production-0000",
            HOTMART_ENABLED=False,
        )
