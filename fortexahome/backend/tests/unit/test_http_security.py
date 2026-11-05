from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.permissions import can, require_owner
from fastapi import HTTPException
from types import SimpleNamespace


def test_cookie_authenticated_write_rejects_cross_site(monkeypatch):
    monkeypatch.setattr(main, "check_database", lambda: None)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
            json={},
        )
    assert response.status_code == 403


def test_webhook_path_has_own_auth_and_is_not_browser_origin_auth(monkeypatch):
    monkeypatch.setattr(main, "check_database", lambda: None)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/webhooks/payments/hmac_sandbox",
            headers={"Origin": "https://provider.example", "Sec-Fetch-Site": "cross-site"},
            content=b"{}",
        )
    assert response.status_code == 401


def test_application_startup_stops_when_database_unavailable(monkeypatch):
    monkeypatch.setattr(main.settings, "ENV", "production")
    monkeypatch.setattr(main, "assert_environment_ready", lambda _settings: [])
    monkeypatch.setattr(main, "check_database", lambda: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError, match="offline"):
        with TestClient(main.app):
            pass


def test_application_startup_stops_on_invalid_production_preflight(monkeypatch):
    monkeypatch.setattr(main.settings, "ENV", "production")
    monkeypatch.setattr(main, "check_database", lambda: None)
    with pytest.raises(RuntimeError, match="APP_BASE_URL"):
        with TestClient(main.app):
            pass


def test_authentication_and_owner_authorization(monkeypatch):
    monkeypatch.setattr(main, "check_database", lambda: None)
    with TestClient(main.app) as client:
        response = client.get("/api/v1/account")
    assert response.status_code == 401
    member = SimpleNamespace(role="member")
    assert can(member, "finance:write")
    with pytest.raises(HTTPException) as error:
        require_owner(member)
    assert error.value.status_code == 403
