from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.main import app

pytestmark = pytest.mark.integration


def _policies():
    found = {}
    for route in app.routes:
        policy = getattr(getattr(route, "endpoint", None), "__rate_limit_policy__", None)
        if not policy:
            continue
        for method in route.methods or ():
            found[(route.path, method)] = policy
    return found


def test_route_rate_limit_policy_matrix_is_explicit(integration_database):
    policies = _policies()
    expected = {
        ("/api/v1/auth/activate", "POST"): ("5/hour", 5, 3600, ("ip", "email")),
        ("/api/v1/auth/activate/confirm", "POST"): ("10/minute", 10, 60, ("ip",)),
        ("/api/v1/auth/activate/resend", "POST"): ("5/hour", 5, 3600, ("ip",)),
        ("/api/v1/auth/recover-license", "POST"): ("5/hour", 5, 3600, ("ip", "email")),
        ("/api/v1/auth/recover-license/confirm", "POST"): ("10/minute", 10, 60, ("ip", "email")),
        ("/api/v1/auth/login", "POST"): ("10/minute", 10, 60, ("ip", "email")),
        ("/api/v1/auth/forgot-password", "POST"): ("5/hour", 5, 3600, ("ip", "email")),
        ("/api/v1/auth/reset-password", "POST"): ("10/hour", 10, 3600, ("ip",)),
        ("/api/v1/support/auth/login", "POST"): ("10/minute", 10, 60, ("ip", "email")),
        ("/api/v1/privacy/requests", "POST"): ("5/hour", 5, 3600, ("user", "ip")),
        ("/api/v1/support/orders/{order_id}/recovery-instructions", "POST"): (
            "30/hour", 30, 3600, ("support_operator", "ip")
        ),
        ("/api/v1/webhooks/hotmart", "POST"): ("60/minute", 60, 60, ("ip",)),
        ("/api/v1/webhooks/payments/{provider}", "POST"): ("120/minute", 120, 60, ("ip",)),
    }
    observed = {
        key: (value["spec"], value["limit"], value["window_seconds"], value["keys"])
        for key, value in policies.items()
    }
    assert observed == expected


def test_support_login_uses_distributed_429_with_ip_and_email(integration_database, monkeypatch):
    ip = f"198.51.100.{uuid.uuid4().int % 200 + 20}"
    email = f"support-rate-{uuid.uuid4().hex[:12]}@example.com"
    monkeypatch.setattr(rate_limit, "client_ip", lambda request: ip)
    monkeypatch.setattr(rate_limit.limiter, "enabled", True)
    client = TestClient(app)

    for _ in range(10):
        response = client.post(
            "/api/v1/support/auth/login",
            json={"email": email, "password": "senha-incorreta"},
        )
        assert response.status_code == 401, response.text

    blocked = client.post(
        "/api/v1/support/auth/login",
        json={"email": email, "password": "senha-incorreta"},
    )
    assert blocked.status_code == 429, blocked.text
    assert int(blocked.headers["Retry-After"]) >= 1


def test_hotmart_webhook_uses_distributed_429_per_ip(integration_database, monkeypatch):
    ip = f"203.0.113.{uuid.uuid4().int % 200 + 20}"
    monkeypatch.setattr(rate_limit, "client_ip", lambda request: ip)
    monkeypatch.setattr(rate_limit.limiter, "enabled", True)
    client = TestClient(app)

    blocked = None
    for _ in range(100):
        response = client.post("/api/v1/webhooks/hotmart", json={})
        if response.status_code == 429:
            blocked = response
            break
        assert response.status_code == 503, response.text
    assert blocked is not None
    assert int(blocked.headers["Retry-After"]) >= 1
