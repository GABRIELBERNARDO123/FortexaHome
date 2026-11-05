from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.field_encryption import normalize_email
from app.core.rate_limit import hash_rate_limit_key
from app.models.login_lockout import LoginLockoutState

settings = get_settings()
logger = logging.getLogger("fortexahome.login_lockout")
_SCOPE = "auth.login.lockout"
_CLEANUP_PROBABILITY = 0.01


@dataclass(frozen=True)
class LockoutStatus:
    allowed: bool
    failure_count: int
    retry_after_seconds: int = 0
    locked_until: datetime | None = None
    lock_triggered: bool = False


def _key(email: str) -> str:
    return hash_rate_limit_key(_SCOPE, "account", normalize_email(email))


def lockout_key(email: str) -> str:
    return _key(email)


def _now(db: Session) -> datetime:
    value = db.scalar(select(func.now()))
    if value is None:
        raise RuntimeError("horário do banco indisponível")
    return value


def _cooldown_seconds(failure_count: int) -> int:
    excess = max(0, failure_count - settings.LOGIN_LOCKOUT_FAILURE_THRESHOLD)
    exponent = min(excess, 10)
    return min(
        settings.LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS,
        settings.LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS * (2**exponent),
    )


def _cleanup_expired(db: Session, now: datetime) -> None:
    try:
        db.execute(delete(LoginLockoutState).where(LoginLockoutState.expires_at < now))
    except SQLAlchemyError as exc:
        logger.warning("Limpeza de lockout indisponível (%s)", type(exc).__name__)


def _maybe_cleanup(db: Session, now: datetime) -> None:
    if random.random() < _CLEANUP_PROBABILITY:
        _cleanup_expired(db, now)


def get_status(db: Session, email: str) -> LockoutStatus:
    """Read-only precheck. DB failures fail-open so the main auth path remains available."""
    if not settings.LOGIN_LOCKOUT_ENABLED:
        return LockoutStatus(allowed=True, failure_count=0)
    try:
        row = db.scalar(
            select(LoginLockoutState).where(LoginLockoutState.key_hash == _key(email))
        )
        now = _now(db)
        if row is None or row.expires_at <= now:
            return LockoutStatus(allowed=True, failure_count=0)
        if row.locked_until is not None and row.locked_until > now:
            return LockoutStatus(
                allowed=False,
                failure_count=row.failure_count,
                retry_after_seconds=max(
                    1, math.ceil((row.locked_until - now).total_seconds())
                ),
                locked_until=row.locked_until,
            )
        return LockoutStatus(allowed=True, failure_count=row.failure_count)
    except Exception as exc:
        logger.warning("Lockout de login indisponível (%s); fail-open", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass
        return LockoutStatus(allowed=True, failure_count=0)


def record_failure(db: Session, email: str) -> LockoutStatus:
    if not settings.LOGIN_LOCKOUT_ENABLED:
        return LockoutStatus(allowed=True, failure_count=0)
    key = _key(email)
    try:
        now = _now(db)
        db.execute(
            pg_insert(LoginLockoutState)
            .values(
                key_hash=key,
                failure_count=0,
                locked_until=None,
                last_failure_at=None,
                updated_at=now,
                expires_at=now + timedelta(seconds=settings.LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS),
            )
            .on_conflict_do_nothing(index_elements=["key_hash"])
        )
        row = db.scalar(
            select(LoginLockoutState)
            .where(LoginLockoutState.key_hash == key)
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("estado de lockout não pôde ser criado")

        if row.expires_at <= now:
            row.failure_count = 0
            row.locked_until = None
            row.last_failure_at = None

        old_locked_until = row.locked_until
        row.failure_count = min(
            settings.LOGIN_LOCKOUT_MAX_TRACKED_FAILURES,
            row.failure_count + 1,
        )
        now = _now(db)
        lock_triggered = False
        if row.failure_count >= settings.LOGIN_LOCKOUT_FAILURE_THRESHOLD:
            cooldown = _cooldown_seconds(row.failure_count)
            row.locked_until = now + timedelta(seconds=cooldown)
            lock_triggered = old_locked_until is None or old_locked_until <= now
        else:
            row.locked_until = None
        row.last_failure_at = now
        row.updated_at = now
        row.expires_at = now + timedelta(seconds=settings.LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS)
        _maybe_cleanup(db, now)
        allowed = row.locked_until is None or row.locked_until <= now
        retry_after = (
            0
            if allowed or row.locked_until is None
            else max(1, math.ceil((row.locked_until - now).total_seconds()))
        )
        return LockoutStatus(
            allowed=allowed,
            failure_count=row.failure_count,
            retry_after_seconds=retry_after,
            locked_until=row.locked_until,
            lock_triggered=lock_triggered,
        )
    except Exception as exc:
        logger.warning("Registro de falha de lockout indisponível (%s); fail-open", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass
        return LockoutStatus(allowed=True, failure_count=0)


def record_success(db: Session, email: str) -> None:
    if not settings.LOGIN_LOCKOUT_ENABLED:
        return
    key = _key(email)
    try:
        now = _now(db)
        db.execute(
            pg_insert(LoginLockoutState)
            .values(
                key_hash=key,
                failure_count=0,
                locked_until=None,
                last_failure_at=None,
                updated_at=now,
                expires_at=now + timedelta(seconds=settings.LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS),
            )
            .on_conflict_do_nothing(index_elements=["key_hash"])
        )
        row = db.scalar(
            select(LoginLockoutState)
            .where(LoginLockoutState.key_hash == key)
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("estado de lockout não pôde ser criado")
        row.failure_count = 0
        row.locked_until = None
        row.last_failure_at = None
        row.updated_at = now
        row.expires_at = now + timedelta(seconds=settings.LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS)
        _maybe_cleanup(db, now)
    except Exception as exc:
        logger.warning("Reset de lockout indisponível (%s); fail-open", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass


__all__ = ["LockoutStatus", "get_status", "lockout_key", "record_failure", "record_success"]
