from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar, Token
from typing import Any

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_REQUEST_ID: ContextVar[str] = ContextVar("fortexahome_request_id", default="-")

_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_AUTH_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS_RE = re.compile(r"(?i)(https?://)[^/@\s]+@")
_HEADER_RE = re.compile(
    r"(?im)^(authorization|cookie|set-cookie|x-hotmart-hottok|x-fortexa-signature|x-api-key)\s*:\s*.*$"
)
_ASSIGN_RE = re.compile(
    r"(?i)([\"']?(?:password|passwd|senha|secret|segredo|token|access[_-]?token|refresh[_-]?token|"
    r"authorization|cookie|email|e-mail|cpf|cnpj|document|documento|license[_-]?code|hmac|"
    r"hottok|api[_-]?key|client[_-]?secret|code)[\"']?\s*[=:]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\"'\s,&;}\][]+)"
)
_LICENSE_RE = re.compile(r"\bFH-[A-Za-z0-9-]{8,}\b")
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")

_SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "senha",
    "secret",
    "segredo",
    "token",
    "authorization",
    "cookie",
    "email",
    "e-mail",
    "cpf",
    "cnpj",
    "document",
    "documento",
    "licensecode",
    "codigolicenca",
    "hmac",
    "hottok",
    "apikey",
    "clientsecret",
    "cardnumber",
    "cvv",
    "pan",
    "phone",
    "telefone",
    "address",
    "endereco",
    "buyername",
    "customername",
    "username",
    "fullname",
    "nomecompleto",
    "code",
    "codigo",
)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def valid_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not _REQUEST_ID_RE.fullmatch(candidate):
        return None
    return candidate


def new_request_id() -> str:
    return str(uuid.uuid4())


def get_request_id() -> str:
    return _REQUEST_ID.get()


def set_request_id(value: str) -> Token:
    return _REQUEST_ID.set(value)


def reset_request_id(token: Token) -> None:
    _REQUEST_ID.reset(token)


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if normalized in {"code", "codigo"}:
        return True
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def redact_text(value: str) -> str:
    if not value:
        return value
    redacted = _HEADER_RE.sub(lambda match: f"{match.group(1)}: [REDACTED]", value)
    redacted = _AUTH_RE.sub(lambda match: f"{match.group(1)} [REDACTED]", redacted)
    redacted = _ASSIGN_RE.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    redacted = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", redacted)
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
    redacted = _LICENSE_RE.sub("[REDACTED_LICENSE]", redacted)
    redacted = _JWT_RE.sub("[REDACTED_TOKEN]", redacted)
    redacted = _CPF_RE.sub("[REDACTED_CPF]", redacted)
    redacted = _LONG_HEX_RE.sub("[REDACTED_HASH]", redacted)
    return redacted[:2000]


def redact_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return "[REDACTED_BYTES]"
    if isinstance(value, BaseException):
        return _safe_exception_summary(value)
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_sensitive_key(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_value(item)
        return result
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return f"[REDACTED_OBJECT:{type(value).__name__}]"


def _safe_exception_summary(exc: BaseException) -> str:
    summary = type(exc).__name__
    pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
    if pgcode:
        summary += f" pgcode={pgcode}"
    return f"{summary} (details redacted)"


def _safe_traceback_text(exc: BaseException, tb) -> str:
    frames: list[str] = []
    current = tb
    while current is not None and len(frames) < 20:
        code = current.tb_frame.f_code
        frames.append(f"{code.co_filename}:{current.tb_lineno} in {code.co_name}")
        current = current.tb_next
    header = _safe_exception_summary(exc)
    return header + (("\n" + "\n".join(frames)) if frames else "")


def sanitize_exc_info(exc_info):
    exc_type, exc, tb = exc_info
    return (RuntimeError, RuntimeError(_safe_exception_summary(exc)), tb)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        if record.exc_info:
            _, exc, tb = record.exc_info
            record.exc_text = _safe_traceback_text(exc, tb)
            record.exc_info = None
        record.msg = redact_value(record.msg)
        if record.args:
            record.args = redact_value(record.args)
        return True


def _install_filters_on_logger(name: str) -> None:
    logger = logging.getLogger(name)
    for handler in logger.handlers:
        if not any(isinstance(item, RedactingFilter) for item in handler.filters):
            handler.addFilter(RedactingFilter())


def install_bootstrap_logging_safety() -> None:
    """Install redaction before Settings can raise during application import."""
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        _install_filters_on_logger(name)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def configure_logging(service_name: str) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            f"service={service_name} request_id=%(request_id)s %(message)s"
        ),
    )
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        _install_filters_on_logger(name)
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


__all__ = [
    "RedactingFilter",
    "configure_logging",
    "get_request_id",
    "install_bootstrap_logging_safety",
    "new_request_id",
    "redact_text",
    "redact_value",
    "reset_request_id",
    "sanitize_exc_info",
    "set_request_id",
    "valid_request_id",
]
