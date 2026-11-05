from __future__ import annotations

import io
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.log_safety import RedactingFilter
from app.main import app

pytestmark = pytest.mark.integration


def _capture_root_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(request_id)s %(message)s\n%(exc_text)s"))
    handler.addFilter(RedactingFilter())
    capture_logger = logging.getLogger("fortexahome")
    previous_level = capture_logger.level
    previous_disabled = capture_logger.disabled
    capture_logger.disabled = False
    capture_logger.addHandler(handler)
    capture_logger.setLevel(logging.DEBUG)
    return stream, handler, capture_logger, previous_level, previous_disabled


def _cleanup(handler, capture_logger, previous_level, previous_disabled):
    capture_logger.removeHandler(handler)
    capture_logger.setLevel(previous_level)
    capture_logger.disabled = previous_disabled


def test_unhandled_exception_is_generic_and_logs_are_redacted(monkeypatch):
    stream, handler, capture_logger, previous_level, previous_disabled = _capture_root_logs()
    route = None
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            async def boom():
                raise RuntimeError(
                    "password=Senha#2026 email=buyer@example.com "
                    "Authorization: Bearer secret-token CPF=123.456.789-09"
                )

            route = app.add_api_route("/__test/boom", boom, methods=["GET"])
            response = client.get("/__test/boom", headers={"X-Request-ID": "safe-request-123"})
    finally:
        if route is not None:
            app.router.routes.remove(route)
        _cleanup(handler, capture_logger, previous_level, previous_disabled)

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "safe-request-123"
    body = response.json()
    assert body["detail"] == "Erro interno. Tente novamente em instantes."
    assert body["request_id"] == "safe-request-123"
    assert "traceback" not in response.text.lower()
    logs = stream.getvalue()
    for sensitive in ("Senha#2026", "buyer@example.com", "secret-token", "123.456.789-09"):
        assert sensitive not in logs
    assert "safe-request-123" in logs
    assert "RuntimeError" in logs


def test_sqlalchemy_exception_is_redacted_in_logs():
    stream, handler, capture_logger, previous_level, previous_disabled = _capture_root_logs()
    route = None
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            async def db_boom():
                raise IntegrityError(
                    "INSERT INTO users (email) VALUES (%(email)s)",
                    {"email": "buyer@example.com", "password": "Senha#2026"},
                    Exception("duplicate key value violates unique constraint"),
                )

            route = app.add_api_route("/__test/db-boom", db_boom, methods=["GET"])
            response = client.get("/__test/db-boom", headers={"X-Request-ID": "db-request-1"})
    finally:
        if route is not None:
            app.router.routes.remove(route)
        _cleanup(handler, capture_logger, previous_level, previous_disabled)

    assert response.status_code == 500
    assert response.json()["request_id"] == "db-request-1"
    logs = stream.getvalue()
    assert "buyer@example.com" not in logs
    assert "Senha#2026" not in logs
    assert "duplicate key value" not in logs
    assert "IntegrityError" in logs
    assert "db-request-1" in logs


def test_request_id_header_validation_and_validation_error_correlation():
    with TestClient(app) as client:
        accepted = client.get("/api/v1/health", headers={"X-Request-ID": "valid-request.1"})
        assert accepted.headers["X-Request-ID"] == "valid-request.1"

        invalid = client.get("/api/v1/health", headers={"X-Request-ID": "bad value with spaces"})
        assert invalid.headers["X-Request-ID"] != "bad value with spaces"
        assert len(invalid.headers["X-Request-ID"]) == 36

        validation = client.post(
            "/api/v1/auth/login",
            json={},
            headers={"X-Request-ID": "validation-request-1"},
        )
        assert validation.status_code == 422
        assert validation.headers["X-Request-ID"] == "validation-request-1"
        assert validation.json()["request_id"] == "validation-request-1"
        assert "input" not in validation.text.lower()
