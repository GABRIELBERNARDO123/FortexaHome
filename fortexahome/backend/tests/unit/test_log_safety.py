from __future__ import annotations

import io
import logging
import threading

from app.core.log_safety import (
    RedactingFilter,
    get_request_id,
    new_request_id,
    redact_text,
    redact_value,
    reset_request_id,
    set_request_id,
    valid_request_id,
)


def test_redact_text_removes_common_sensitive_values():
    raw = (
        "email=person@example.com password=Senha#2026 token=abc123 "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature "
        "Cookie: fh_session=secret; HOTTOK=xyz CPF=123.456.789-09 "
        "license=FH-ABCD-EFGH-IJKL api_key=key123 "
        "url=https://user:pass@example.com/path?token=abc&email=user@example.com"
    )
    redacted = redact_text(raw)
    for sensitive in (
        "person@example.com",
        "Senha#2026",
        "abc123",
        "eyJhbGciOiJIUzI1NiJ9",
        "fh_session=secret",
        "HOTTOK=xyz",
        "123.456.789-09",
        "FH-ABCD-EFGH-IJKL",
        "key123",
        "user:pass",
    ):
        assert sensitive not in redacted
    assert "[REDACTED]" in redacted or "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_LICENSE]" in redacted


def test_redact_text_handles_quoted_values_and_multi_part_authorization():
    raw = (
        "password='senha com espaço' "
        "\"client_secret\": \"segredo composto\" "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature "
        "payload={'email': 'buyer@example.com', 'code': 'ABC123'}"
    )
    redacted = redact_text(raw)
    for sensitive in (
        "senha com espaço",
        "segredo composto",
        "eyJhbGciOiJIUzI1NiJ9",
        "buyer@example.com",
        "ABC123",
    ):
        assert sensitive not in redacted
    assert redacted.count("[REDACTED]") >= 3


def test_redact_value_recurses_into_nested_structures():
    value = {
        "safe": "visible",
        "password": "secret",
        "nested": {
            "buyer_email": "person@example.com",
            "Authorization": "Bearer token-value",
            "items": [{"cpf": "123.456.789-09", "note": "ok"}],
        },
    }
    redacted = redact_value(value)
    assert redacted["safe"] == "visible"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"]["buyer_email"] == "[REDACTED]"
    assert redacted["nested"]["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["items"][0]["cpf"] == "[REDACTED]"
    assert redacted["nested"]["items"][0]["note"] == "ok"


def test_filter_sanitizes_message_args_and_exception_traceback():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(request_id)s %(message)s\n%(exc_text)s"))
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("test.log_safety.filter")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    token = set_request_id("request-123")
    try:
        try:
            raise RuntimeError("password=senha123 email=person@example.com Authorization: Bearer secret")
        except RuntimeError as exc:
            logger.error(
                "falha email=%(email)s token=%(token)s",
                {"email": "person@example.com", "token": "token-value"},
                exc_info=exc,
            )
    finally:
        reset_request_id(token)
    output = stream.getvalue()
    assert "person@example.com" not in output
    assert "senha123" not in output
    assert "token-value" not in output
    assert "Bearer secret" not in output
    assert "request-123" in output
    assert "RuntimeError (details redacted)" in output
    logger.handlers.clear()


def test_request_id_validation_generates_safe_identifier():
    assert valid_request_id("req-123.abc:def") == "req-123.abc:def"
    assert valid_request_id("bad value with spaces") is None
    assert valid_request_id("x" * 65) is None
    assert valid_request_id("bad\ninjection") is None
    generated = new_request_id()
    assert generated != "bad value with spaces"
    assert len(generated) == 36


def test_request_id_context_is_isolated_between_threads():
    barrier = threading.Barrier(2)
    seen: list[str] = []

    def worker(value: str) -> None:
        token = set_request_id(value)
        try:
            barrier.wait(timeout=5)
            seen.append(get_request_id())
        finally:
            reset_request_id(token)

    threads = [
        threading.Thread(target=worker, args=("request-a",)),
        threading.Thread(target=worker, args=("request-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert sorted(seen) == ["request-a", "request-b"]
