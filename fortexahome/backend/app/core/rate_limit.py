from __future__ import annotations

import functools
import hmac
import inspect
import ipaddress
import logging
import math
import random
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import SessionLocal, reapply_db_context
from app.core.field_encryption import normalize_email
from app.models.rate_limit import RateLimitBucket

logger = logging.getLogger("fortexahome.rate_limit")
settings = get_settings()

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour|day)s?\s*$", re.IGNORECASE)
_WINDOW_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_CLEANUP_PROBABILITY = 0.01


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


def _trusted_proxy(remote: str) -> bool:
    configured = settings.trusted_proxy_ips_list
    if remote in configured:
        return True
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    for item in configured:
        try:
            if address in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    remote = request.client.host if request.client else "unknown"
    if not _trusted_proxy(remote):
        return remote

    real_ip = _valid_ip(request.headers.get("x-real-ip", ""))
    if real_ip:
        return real_ip

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # O Nginx sobrescreve X-Forwarded-For com o endereço do cliente.
        # O último endereço válido é o mais próximo do proxy confiável.
        for part in reversed(forwarded.split(",")):
            candidate = _valid_ip(part)
            if candidate:
                return candidate
    return remote


def parse_rate(spec: str) -> RateLimitPolicy:
    match = _RATE_RE.match(spec)
    if not match:
        raise ValueError(f"Especificação de rate limit inválida: {spec!r}")
    limit = int(match.group(1))
    if limit <= 0:
        raise ValueError("O limite deve ser positivo")
    window_seconds = _WINDOW_SECONDS[match.group(2).lower()]
    return RateLimitPolicy(limit=limit, window_seconds=window_seconds)


def hash_rate_limit_key(scope: str, kind: str, value: str) -> str:
    message = f"{scope}\x1f{kind}\x1f{value}".encode("utf-8")
    return hmac.new(settings.RATE_LIMIT_HMAC_KEY.encode("utf-8"), message, sha256).hexdigest()


def _cleanup_expired() -> None:
    try:
        with SessionLocal() as db:
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at < func.now()))
            db.commit()
    except Exception as exc:
        logger.warning("Limpeza de rate limit indisponível (%s)", type(exc).__name__)


def _consume_in_session(
    db: Session,
    hashes: list[str],
    *,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:
    capacity = float(limit)
    refill_per_second = limit / window_seconds
    expires_after = timedelta(seconds=max(window_seconds, 1))
    timeout = f"{settings.RATE_LIMIT_DB_TIMEOUT_MS}ms"
    db.execute(text("SELECT set_config('statement_timeout', :value, true)"), {"value": timeout})
    db.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": timeout})
    now = db.scalar(select(func.now()))
    if now is None:
        raise RuntimeError("horário do banco indisponível")

    denied_retry = 0
    for key_hash in hashes:
        db.execute(
            pg_insert(RateLimitBucket)
            .values(
                key_hash=key_hash,
                tokens=capacity,
                updated_at=now,
                expires_at=now + expires_after,
            )
            .on_conflict_do_nothing(index_elements=["key_hash"])
        )
        row = db.scalar(
            select(RateLimitBucket)
            .where(RateLimitBucket.key_hash == key_hash)
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("bucket de rate limit não pôde ser criado")

        elapsed = max(0.0, (now - row.updated_at).total_seconds())
        available = min(capacity, row.tokens + elapsed * refill_per_second)
        if available >= 1.0:
            row.tokens = available - 1.0
        else:
            row.tokens = available
            wait = math.ceil((1.0 - available) / refill_per_second)
            denied_retry = max(denied_retry, max(1, wait))
        row.updated_at = now
        row.expires_at = now + expires_after

    db.commit()
    if random.random() < _CLEANUP_PROBABILITY:
        _cleanup_expired()
    reapply_db_context(db)
    return RateLimitDecision(allowed=denied_retry == 0, retry_after=denied_retry)


def consume_rate_limit_keys(
    key_hashes: Iterable[str],
    *,
    limit: int,
    window_seconds: int,
    session: Session | None = None,
) -> RateLimitDecision:
    hashes = sorted({item for item in key_hashes if item})
    if not hashes:
        return RateLimitDecision(allowed=True)

    try:
        if session is not None:
            return _consume_in_session(session, hashes, limit=limit, window_seconds=window_seconds)
        with SessionLocal() as db:
            return _consume_in_session(db, hashes, limit=limit, window_seconds=window_seconds)
    except Exception as exc:
        if session is not None:
            try:
                session.rollback()
                reapply_db_context(session)
            except Exception:
                pass
        # O banco já é necessário para os fluxos protegidos. Uma falha apenas do
        # limiter não deve transformar indisponibilidade transitória em bloqueio.
        logger.warning("Rate limiter indisponível (%s); aplicando fail-open", type(exc).__name__)
        return RateLimitDecision(allowed=True)


def _identity_value(kind: str, kwargs: dict) -> str | None:
    request = kwargs.get("request")
    if kind == "ip":
        return client_ip(request) if request is not None else None
    if kind == "email":
        payload = kwargs.get("payload")
        value = getattr(payload, "email", None)
        return normalize_email(value) if isinstance(value, str) and value.strip() else None

    ctx = kwargs.get("ctx")
    if kind == "support_operator":
        operator = getattr(ctx, "operator", None)
        value = getattr(operator, "id", None)
    elif kind == "user":
        user = getattr(ctx, "user", None)
        value = getattr(user, "id", None)
    elif kind == "tenant":
        user = getattr(ctx, "user", None)
        value = getattr(user, "tenant_id", None)
    elif kind == "session":
        session = getattr(ctx, "session", None)
        value = getattr(session, "id", None)
    else:
        raise ValueError(f"Tipo de identidade de rate limit desconhecido: {kind}")
    return str(value) if value else None


def enforce_rate_limit(
    *,
    request: Request | None,
    kwargs: dict,
    scope: str,
    policy: RateLimitPolicy,
    keys: tuple[str, ...],
    session: Session | None = None,
) -> None:
    if request is None:
        return
    identities: list[tuple[str, str]] = []
    for kind in keys:
        value = _identity_value(kind, kwargs)
        if value:
            identities.append((kind, value))
    if not identities:
        return

    hashes = [hash_rate_limit_key(scope, kind, value) for kind, value in identities]
    decision = consume_rate_limit_keys(
        hashes,
        limit=policy.limit,
        window_seconds=policy.window_seconds,
        session=session,
    )
    if not decision.allowed:
        retry_after = max(1, decision.retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas requisições. Tente novamente em instantes.",
            headers={"Retry-After": str(retry_after)},
        )


class RateLimiter:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled

    def limit(
        self,
        spec: str,
        *,
        keys: tuple[str, ...] = ("ip",),
        scope: str | None = None,
    ) -> Callable:
        policy = parse_rate(spec)

        def decorator(func: Callable) -> Callable:
            scope_name = scope or f"{func.__module__}.{func.__name__}"

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    if self.enabled:
                        await run_in_threadpool(
                            enforce_rate_limit,
                            request=kwargs.get("request"),
                            kwargs=kwargs,
                            scope=scope_name,
                            policy=policy,
                            keys=keys,
                            session=None,
                        )
                    return await func(*args, **kwargs)

                async_wrapper.__rate_limit_policy__ = {
                    "scope": scope_name,
                    "spec": spec,
                    "limit": policy.limit,
                    "window_seconds": policy.window_seconds,
                    "keys": keys,
                }
                return async_wrapper

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                if self.enabled:
                    enforce_rate_limit(
                        request=kwargs.get("request"),
                        kwargs=kwargs,
                        scope=scope_name,
                        policy=policy,
                        keys=keys,
                        session=kwargs.get("db"),
                    )
                return func(*args, **kwargs)

            wrapper.__rate_limit_policy__ = {
                "scope": scope_name,
                "spec": spec,
                "limit": policy.limit,
                "window_seconds": policy.window_seconds,
                "keys": keys,
            }
            return wrapper

        return decorator


limiter = RateLimiter(enabled=settings.RATE_LIMIT_ENABLED)
