from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.main import app

pytestmark = pytest.mark.integration


def _key(scope: str, kind: str = "ip") -> str:
    return rate_limit.hash_rate_limit_key(scope, kind, uuid.uuid4().hex)


def test_concurrent_requests_share_one_atomic_token_bucket(integration_database):
    key = _key("test.concurrent")

    def consume(_: int):
        return rate_limit.consume_rate_limit_keys([key], limit=5, window_seconds=3600)

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(consume, range(20)))

    allowed = [item for item in decisions if item.allowed]
    denied = [item for item in decisions if not item.allowed]
    assert len(allowed) == 5
    assert len(denied) == 15
    assert all(item.retry_after >= 1 for item in denied)


def test_different_keys_and_scopes_are_isolated(integration_database):
    first = _key("test.isolated")
    second = _key("test.isolated")
    other_scope = _key("test.isolated.other")

    assert rate_limit.consume_rate_limit_keys([first], limit=1, window_seconds=3600).allowed
    assert not rate_limit.consume_rate_limit_keys([first], limit=1, window_seconds=3600).allowed
    assert rate_limit.consume_rate_limit_keys([second], limit=1, window_seconds=3600).allowed
    assert rate_limit.consume_rate_limit_keys([other_scope], limit=1, window_seconds=3600).allowed


def test_token_bucket_refills_after_window(integration_database):
    key = _key("test.refill")
    assert rate_limit.consume_rate_limit_keys([key], limit=1, window_seconds=1).allowed
    denied = rate_limit.consume_rate_limit_keys([key], limit=1, window_seconds=1)
    assert not denied.allowed and denied.retry_after >= 1
    time.sleep(1.2)
    assert rate_limit.consume_rate_limit_keys([key], limit=1, window_seconds=1).allowed


def test_two_api_clients_share_limit_and_return_retry_after(integration_database, monkeypatch):
    ip = f"203.0.113.{uuid.uuid4().int % 200 + 20}"
    monkeypatch.setattr(rate_limit, "client_ip", lambda request: ip)
    monkeypatch.setattr(rate_limit.limiter, "enabled", True)
    clients = [TestClient(app), TestClient(app)]

    for index in range(10):
        email = f"rate-limit-{uuid.uuid4().hex[:12]}@example.com"
        response = clients[index % 2].post(
            "/api/v1/auth/login",
            json={"email": email, "password": "SenhaErrada#2026"},
        )
        assert response.status_code == 401, response.text

    blocked = clients[0].post(
        "/api/v1/auth/login",
        json={"email": f"rate-limit-{uuid.uuid4().hex[:12]}@example.com", "password": "SenhaErrada#2026"},
    )
    assert blocked.status_code == 429, blocked.text
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["detail"] == "Muitas requisições. Tente novamente em instantes."
