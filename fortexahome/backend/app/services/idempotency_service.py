from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Header, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_token
from app.models.idempotency import IdempotencyRecord
from app.models.user import User

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(alias="Idempotency-Key"),
]

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MAX_KEY_LENGTH = 128


def validate_key(raw_key: str | None) -> str | None:
    if raw_key is None:
        return None
    key = raw_key.strip()
    if not key or len(key) > _MAX_KEY_LENGTH or not _KEY_RE.fullmatch(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key inválida. Use de 1 a 128 caracteres [A-Za-z0-9._:-].",
        )
    return key


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def request_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _expiry(now: datetime | None = None) -> datetime:
    settings = get_settings()
    return (now or datetime.now(timezone.utc)) + timedelta(hours=settings.IDEMPOTENCY_RETENTION_HOURS)


def execute(
    db: Session,
    user: User,
    *,
    operation: str,
    key: str | None,
    payload: Any,
    effect: Callable[[], tuple[dict, str, uuid.UUID]],
) -> dict:
    """Execute a financial effect with an optional atomic idempotency guard.

    The idempotency row and the financial effect are committed in the same
    PostgreSQL transaction. A failed effect rolls back both, so no permanent
    ``processing`` state is left behind.
    """
    validated_key = validate_key(key)
    if validated_key is None:
        try:
            response, _, _ = effect()
            db.commit()
            return response
        except Exception:
            db.rollback()
            raise

    key_hash = hash_token(validated_key)
    fingerprint = request_fingerprint(payload)
    now = datetime.now(timezone.utc)
    expires_at = _expiry(now)
    scope = (
        IdempotencyRecord.tenant_id == user.tenant_id,
        IdempotencyRecord.user_id == user.id,
        IdempotencyRecord.operation == operation,
        IdempotencyRecord.key_hash == key_hash,
    )

    inserted_id = db.scalar(
        pg_insert(IdempotencyRecord)
        .values(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            user_id=user.id,
            operation=operation,
            key_hash=key_hash,
            fingerprint=fingerprint,
            status="processing",
            created_at=now,
            expires_at=expires_at,
        )
        .on_conflict_do_nothing(constraint="uq_idempotency_scope_key")
        .returning(IdempotencyRecord.id)
    )

    record: IdempotencyRecord | None
    if inserted_id is not None:
        record = db.get(IdempotencyRecord, inserted_id)
    else:
        record = db.scalar(select(IdempotencyRecord).where(*scope).with_for_update())
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operação idempotente em conflito. Tente novamente.",
            )
        if record.expires_at <= now:
            record.fingerprint = fingerprint
            record.status = "processing"
            record.resource_type = None
            record.resource_id = None
            record.response_payload = None
            record.completed_at = None
            record.created_at = now
            record.expires_at = expires_at
        else:
            if not hmac.compare_digest(record.fingerprint, fingerprint):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key reutilizada com parâmetros diferentes.",
                )
            if record.status != "completed" or record.response_payload is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Operação idempotente em andamento. Tente novamente.",
                )
            return record.response_payload

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operação idempotente em conflito. Tente novamente.",
        )

    try:
        response, resource_type, resource_id = effect()
        record.status = "completed"
        record.resource_type = resource_type
        record.resource_id = resource_id
        record.response_payload = jsonable_encoder(response)
        record.completed_at = datetime.now(timezone.utc)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def purge_expired(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID | None = None) -> int:
    """Delete expired idempotency records for the current tenant scope.

    The idempotency row never owns the financial effect; deleting an expired
    row does not remove or revert any transaction, bill, goal or movement.
    """
    from sqlalchemy import delete

    conditions = [
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.expires_at < datetime.now(timezone.utc),
    ]
    if user_id is not None:
        conditions.append(IdempotencyRecord.user_id == user_id)
    result = db.execute(delete(IdempotencyRecord).where(*conditions))
    return int(result.rowcount or 0)


__all__ = [
    "IdempotencyKeyHeader",
    "execute",
    "purge_expired",
    "request_fingerprint",
    "validate_key",
]
