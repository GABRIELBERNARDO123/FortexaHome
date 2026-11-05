from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from app.core import rate_limit
from app.core.rate_limit import client_ip


def request(remote: str, **headers: str):
    return SimpleNamespace(client=SimpleNamespace(host=remote), headers=Headers(headers))


def test_private_client_cannot_spoof_forwarding_headers():
    assert client_ip(request("10.0.0.12", **{"X-Real-IP": "203.0.113.4"})) == "10.0.0.12"
    assert client_ip(request("127.0.0.1", **{"X-Forwarded-For": "198.51.100.3"})) == "127.0.0.1"


def test_forwarded_headers_are_used_only_for_explicit_proxy(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "TRUSTED_PROXY_IPS", "172.20.0.0/24")
    assert client_ip(request("172.20.0.10", **{"X-Real-IP": "203.0.113.4"})) == "203.0.113.4"
    assert client_ip(
        request("172.20.0.10", **{"X-Forwarded-For": "192.0.2.8, 198.51.100.5"})
    ) == "198.51.100.5"
    assert client_ip(request("172.20.1.10", **{"X-Real-IP": "203.0.113.4"})) == "172.20.1.10"


def test_parse_rate_accepts_supported_windows_and_rejects_invalid_specs():
    assert rate_limit.parse_rate("5/hour").limit == 5
    assert rate_limit.parse_rate("10/minute").window_seconds == 60
    assert rate_limit.parse_rate("2/seconds").window_seconds == 1
    assert rate_limit.parse_rate("1/day").window_seconds == 86400
    for invalid in ("0/minute", "abc", "5/week", "10"):
        with pytest.raises(ValueError):
            rate_limit.parse_rate(invalid)


def test_hashed_key_is_scoped_and_does_not_expose_identifier(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "RATE_LIMIT_HMAC_KEY", "k" * 40)
    first = rate_limit.hash_rate_limit_key("auth.login", "email", "person@example.test")
    same = rate_limit.hash_rate_limit_key("auth.login", "email", "person@example.test")
    other_scope = rate_limit.hash_rate_limit_key("auth.activate", "email", "person@example.test")
    other_kind = rate_limit.hash_rate_limit_key("auth.login", "ip", "person@example.test")
    assert first == same
    assert first != other_scope
    assert first != other_kind
    assert "person" not in first and "@" not in first
    assert len(first) == 64


def test_rate_limit_decorator_raises_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(
        rate_limit,
        "consume_rate_limit_keys",
        lambda *args, **kwargs: rate_limit.RateLimitDecision(False, 42),
    )
    limiter = rate_limit.RateLimiter(enabled=True)

    @limiter.limit("2/minute", keys=("ip",), scope="test.scope")
    def endpoint(request, payload=None):
        return "ok"

    with pytest.raises(HTTPException) as error:
        endpoint(request=request("203.0.113.9"))
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "42"}


def test_rate_limit_decorator_combines_ip_and_normalized_email(monkeypatch):
    captured: list[list[str]] = []

    def fake_consume(keys, **kwargs):
        captured.append(list(keys))
        return rate_limit.RateLimitDecision(True)

    monkeypatch.setattr(rate_limit, "consume_rate_limit_keys", fake_consume)
    limiter = rate_limit.RateLimiter(enabled=True)

    @limiter.limit("2/minute", keys=("ip", "email"), scope="test.scope")
    def endpoint(request, payload=None):
        return "ok"

    endpoint(
        request=request("203.0.113.9"),
        payload=SimpleNamespace(email="  Person@Example.Test "),
    )
    assert len(captured) == 1
    assert len(captured[0]) == 2


def test_rate_limit_disabled_does_not_touch_storage(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("storage não deveria ser chamado")

    monkeypatch.setattr(rate_limit, "consume_rate_limit_keys", fail)
    limiter = rate_limit.RateLimiter(enabled=False)

    @limiter.limit("1/minute", keys=("ip",), scope="test.scope")
    def endpoint(request, payload=None):
        return "ok"

    assert endpoint(request=request("203.0.113.9")) == "ok"


def test_storage_failure_fails_open(monkeypatch):
    def unavailable():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(rate_limit, "SessionLocal", unavailable)
    decision = rate_limit.consume_rate_limit_keys(["a" * 64], limit=1, window_seconds=60)
    assert decision.allowed is True
    assert decision.retry_after == 0
