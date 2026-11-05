from __future__ import annotations

import json
import random

import httpx
import pytest

from app.integrations.payments.hotmart_api import (
    HotmartApiClient,
    HotmartApiConfig,
    HotmartApiError,
    HotmartAuthError,
    HotmartResponseError,
    HotmartTransientError,
)
from app.services.hotmart_reconciliation_service import decide_reconciliation


def config(**overrides) -> HotmartApiConfig:
    values = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "environment": "production",
        "timeout_seconds": 5,
        "max_attempts": 3,
        "backoff_base_seconds": 0.01,
    }
    values.update(overrides)
    return HotmartApiConfig(**values)


def token_response() -> httpx.Response:
    return httpx.Response(200, json={"access_token": "token-1", "expires_in": 3600})


def history_response(status: str = "APPROVED", transaction: str = "TX-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "items": [
                {
                    "product": {"id": 1234567, "name": "Produto"},
                    "buyer": {"email": "nao-deve-ser-lido@example.com", "name": "Comprador"},
                    "purchase": {
                        "transaction": transaction,
                        "status": status,
                        "order_date": 1700000000000,
                        "approved_date": 1700000100000,
                        "price": {"value": 199.9, "currency_code": "brl"},
                    },
                }
            ],
            "page_info": {"results_per_page": 5},
        },
    )


def make_client(handler, *, sleeps=None, cfg=None, rng=None):
    transport = httpx.MockTransport(handler)
    return HotmartApiClient(
        cfg or config(),
        client=httpx.Client(transport=transport),
        sleep=(sleeps if sleeps is not None else []).append if isinstance(sleeps, list) else sleeps,
        rng=rng or random.Random(1),
    )


def test_fetch_uses_transaction_filter_without_status_filter():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        captured.update(dict(request.url.params))
        return history_response()

    assert make_client(handler).fetch_transaction("TX-1").status == "APPROVED"
    assert captured["transaction"] == "TX-1"
    assert "transaction_status" not in captured
    assert captured["max_results"] == "5"


def test_token_is_cached_and_reused():
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.path.endswith("/oauth/token"):
            auth_calls += 1
            return token_response()
        assert request.headers["Authorization"] == "Bearer token-1"
        return history_response()

    client = make_client(handler)
    assert client.fetch_transaction("TX-1").status == "APPROVED"
    assert client.fetch_transaction("TX-1").status == "APPROVED"
    assert auth_calls == 1


def test_401_refreshes_token_once_after_invalidation():
    auth_calls = 0
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, api_calls
        if request.url.path.endswith("/oauth/token"):
            auth_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{auth_calls}", "expires_in": 3600})
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(401, json={"error": "token_expired"})
        return history_response()

    client = make_client(handler)
    assert client.fetch_transaction("TX-1").status == "APPROVED"
    assert auth_calls == 2
    assert api_calls == 2


def test_404_is_non_retryable_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        return httpx.Response(404, json={"error": "not_found"})

    client = make_client(handler)
    with pytest.raises(HotmartApiError) as error:
        client.fetch_transaction("TX-1")
    assert error.value.http_status == 404
    assert error.value.code == "not_found"


def test_403_is_non_retryable_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        return httpx.Response(403, json={"error": "unauthorized_client"})

    client = make_client(handler)
    with pytest.raises(HotmartAuthError) as error:
        client.fetch_transaction("TX-1")
    assert error.value.http_status == 403
    assert error.value.code == "unauthorized_client"


def test_429_honors_retry_after_and_retries():
    sleeps: list[float] = []
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(429, headers={"Retry-After": "5"}, json={"error": "too_many_requests"})
        return history_response()

    client = make_client(handler, sleeps=sleeps)
    assert client.fetch_transaction("TX-1").status == "APPROVED"
    assert sleeps == [5.0]
    assert api_calls == 2


def test_5xx_exhausts_attempts_as_transient_error():
    api_calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        api_calls += 1
        return httpx.Response(503, json={"error": "internal_server_error"})

    client = make_client(handler, sleeps=sleeps, cfg=config(max_attempts=3))
    with pytest.raises(HotmartTransientError) as error:
        client.fetch_transaction("TX-1")
    assert error.value.retryable is True
    assert api_calls == 3
    assert len(sleeps) == 2


def test_timeout_is_retryable_and_bounded():
    api_calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        api_calls += 1
        raise httpx.TimeoutException("timeout", request=request)

    client = make_client(handler, sleeps=sleeps, cfg=config(max_attempts=2))
    with pytest.raises(HotmartTransientError):
        client.fetch_transaction("TX-1")
    assert api_calls == 2
    assert len(sleeps) == 1


def test_malformed_json_is_response_error_without_retry():
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        api_calls += 1
        return httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})

    client = make_client(handler)
    with pytest.raises(HotmartResponseError) as error:
        client.fetch_transaction("TX-1")
    assert error.value.code == "malformed_json"
    assert api_calls == 1


def test_missing_credentials_fails_without_http_call():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = make_client(handler, cfg=config(client_id="", client_secret=""))
    with pytest.raises(HotmartAuthError) as error:
        client.fetch_transaction("TX-1")
    assert error.value.code == "missing_credentials"
    assert calls == 0


def test_transaction_not_returned_and_conflicting_states():
    def not_found(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        return httpx.Response(200, json={"items": []})

    assert make_client(not_found).fetch_transaction("TX-1") is None

    def conflict(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return token_response()
        first = history_response("APPROVED", "TX-1").json()
        second = history_response("REFUNDED", "TX-1").json()
        return httpx.Response(200, json={"items": first["items"] + second["items"]})

    with pytest.raises(HotmartResponseError) as error:
        make_client(conflict).fetch_transaction("TX-1")
    assert error.value.code == "multiple_transaction_states"


def test_observation_parses_only_commercial_fields():
    client = make_client(
        lambda request: token_response()
        if request.url.path.endswith("/oauth/token")
        else history_response()
    )
    observation = client.fetch_transaction("TX-1")
    assert observation is not None
    assert observation.transaction == "TX-1"
    assert observation.status == "APPROVED"
    assert observation.product_id == 1234567
    assert observation.product_ucode is None
    assert observation.price_cents == 19990
    assert observation.price_currency == "BRL"
    assert observation.order_date is not None
    assert observation.approved_date is not None
    assert "buyer" not in observation.__dict__


@pytest.mark.parametrize(
    ("remote", "local", "license", "email", "comparison", "action"),
    [
        ("APPROVED", "paid", "active", True, "consistent", "no_change"),
        ("APPROVED", "pending", None, True, "correctable", "approval"),
        ("APPROVED", "pending", "suspended", True, "correctable", "approval"),
        ("APPROVED", "pending", None, False, "manual_review", "manual"),
        ("APPROVED", "refunded", "cancelled", True, "manual_review", "manual"),
        ("REFUNDED", "paid", "active", True, "correctable", "terminal:REFUNDED"),
        ("CHARGEBACK", "paid", "active", True, "correctable", "terminal:CHARGEBACK"),
        ("PROTESTED", "pending", None, True, "correctable", "terminal:PROTESTED"),
        ("CANCELLED", "cancelled", "cancelled", True, "consistent", "no_change"),
        ("EXPIRED", "cancelled", "cancelled", True, "consistent", "no_change"),
        ("REFUNDED", "chargeback", "suspended", True, "manual_review", "manual"),
        ("BLOCKED", "paid", "active", True, "manual_review", "manual"),
        ("PARTIALLY_REFUNDED", "paid", "active", True, "manual_review", "manual"),
        ("NO_FUNDS", "pending", None, True, "manual_review", "manual"),
        ("WAITING_PAYMENT", "pending", None, True, "consistent", "no_change"),
        ("WAITING_PAYMENT", "paid", "active", True, "manual_review", "manual"),
        ("COMPLETE", "paid", "active", True, "consistent", "no_change"),
        ("ALIEN_STATUS", "paid", "active", True, "manual_review", "manual"),
        ("REFUNDED", "refunded", "cancelled", True, "consistent", "no_change"),
    ],
)
def test_status_decisions_are_conservative(remote, local, license, email, comparison, action):
    actual_comparison, actual_action, _ = decide_reconciliation(local, license, email, remote)
    assert (actual_comparison, actual_action) == (comparison, action)
