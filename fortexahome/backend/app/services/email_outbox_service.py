from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import set_db_context
from app.core.field_encryption import decrypt_text, encrypt_text
from app.models.email_outbox import EmailOutbox
from app.services import email_service

settings = get_settings()
_FIELD = "email_outbox.payload"
_LICENSE_DELIVERY = "license_delivery"
_DELIVERY_CANCELLABLE_STATUSES = ("pending", "processing")
_LICENSE_DELIVERY_DEFER_SECONDS = 60


def enqueue_email(
    db: Session,
    *,
    event_type: str,
    payload: dict[str, str],
    idempotency_key: str,
    aggregate_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> EmailOutbox:
    now = datetime.now(timezone.utc)
    row = EmailOutbox(
        event_type=event_type,
        idempotency_key=idempotency_key,
        aggregate_id=aggregate_id,
        status="pending",
        payload_encrypted=encrypt_text(json.dumps(payload, separators=(",", ":")), _FIELD),
        attempt_count=0,
        max_attempts=settings.OUTBOX_MAX_ATTEMPTS,
        next_attempt_at=now,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return row


def cancel_activation_emails(db: Session, activation_id: uuid.UUID) -> None:
    db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.event_type == "activation_verification",
            EmailOutbox.aggregate_id == activation_id,
            EmailOutbox.status.in_(("pending", "processing")),
        )
        .values(status="cancelled", processed_at=datetime.now(timezone.utc), payload_encrypted=None,
                claimed_by=None, lease_until=None, last_error="activation_changed")
    )


def _set_license_context(db: Session, license_id: uuid.UUID) -> None:
    set_db_context(db, outbox_license_id=license_id)


def cancel_license_delivery(db: Session, license_id: uuid.UUID, *, reason: str) -> None:
    """Cancel only license_delivery messages for one license, in the caller transaction."""
    _set_license_context(db, license_id)
    db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.event_type == _LICENSE_DELIVERY,
            EmailOutbox.aggregate_id == license_id,
            EmailOutbox.status.in_(_DELIVERY_CANCELLABLE_STATUSES),
        )
        .values(
            status="cancelled",
            processed_at=datetime.now(timezone.utc),
            payload_encrypted=None,
            claimed_by=None,
            lease_until=None,
            last_error=reason[:64],
        )
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_batch(db: Session, worker_id: uuid.UUID, *, batch_size: int | None = None) -> list[uuid.UUID]:
    now = _utcnow()
    retention_before = now - timedelta(days=settings.OUTBOX_DEAD_PAYLOAD_RETENTION_DAYS)
    db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.status == "dead",
            EmailOutbox.payload_encrypted.is_not(None),
            EmailOutbox.processed_at <= retention_before,
        )
        .values(payload_encrypted=None)
    )
    db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.status == "pending",
            EmailOutbox.expires_at.is_not(None),
            EmailOutbox.expires_at <= now,
        )
        .values(status="cancelled", processed_at=now, payload_encrypted=None, last_error="expired")
    )
    db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.status == "processing",
            EmailOutbox.lease_until <= now,
            EmailOutbox.attempt_count >= EmailOutbox.max_attempts,
        )
        .values(status="dead", processed_at=now, claimed_by=None, lease_until=None,
                last_error="lease_exhausted")
    )
    rows = list(
        db.scalars(
            select(EmailOutbox)
            .where(
                EmailOutbox.attempt_count < EmailOutbox.max_attempts,
                or_(
                    (EmailOutbox.status == "pending") & (EmailOutbox.next_attempt_at <= now),
                    (EmailOutbox.status == "processing") & (EmailOutbox.lease_until <= now),
                ),
            )
            .order_by(EmailOutbox.created_at)
            .limit(batch_size or settings.OUTBOX_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for row in rows:
        row.status = "processing"
        row.attempt_count += 1
        row.processed_at = now
        row.claimed_by = worker_id
        row.lease_until = now + timedelta(seconds=settings.OUTBOX_LEASE_SECONDS)
    db.commit()
    return [row.id for row in rows]


def _payload(row: EmailOutbox) -> dict[str, str]:
    decoded = decrypt_text(row.payload_encrypted, _FIELD)
    if decoded is None:
        raise email_service.PermanentEmailDeliveryError("payload_missing")
    value = json.loads(decoded)
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise email_service.PermanentEmailDeliveryError("payload_invalid")
    return value


def _load_claim(db: Session, row_id: uuid.UUID, worker_id: uuid.UUID) -> EmailOutbox | None:
    row = db.scalar(select(EmailOutbox).where(EmailOutbox.id == row_id))
    if row is None or row.status != "processing" or row.claimed_by != worker_id:
        return None
    if row.expires_at is not None and row.expires_at <= _utcnow():
        row.status = "cancelled"
        row.processed_at = _utcnow()
        row.payload_encrypted = None
        row.claimed_by = None
        row.lease_until = None
        row.last_error = "expired"
        db.commit()
        return None
    return row


def _password_reset_is_current(db: Session, aggregate_id: uuid.UUID | None) -> bool:
    if aggregate_id is None:
        return False
    db.execute(
        text("SELECT set_config('app.outbox_reset_token_id', :token_id, true)"),
        {"token_id": str(aggregate_id)},
    )
    current = db.execute(
        text("SELECT used_at, expires_at FROM password_reset_tokens WHERE id = :token_id"),
        {"token_id": aggregate_id},
    ).one_or_none()
    return bool(
        current is not None
        and current.used_at is None
        and current.expires_at > _utcnow()
    )


def _backoff_seconds(attempt: int) -> float:
    ceiling = min(settings.OUTBOX_RETRY_MAX_SECONDS, settings.OUTBOX_RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1)))
    return random.uniform(ceiling * 0.5, ceiling)




def _license_delivery_decision(db: Session, license_id: uuid.UUID | None) -> str:
    if license_id is None:
        return "cancel"
    db.execute(
        text("SELECT set_config('app.outbox_license_id', :license_id, true)"),
        {"license_id": str(license_id)},
    )
    license_row = db.execute(
        text("SELECT status, order_id FROM licenses WHERE id = :license_id"),
        {"license_id": license_id},
    ).mappings().one_or_none()
    if license_row is None:
        return "cancel"
    license_status = license_row["status"]
    order_id = license_row["order_id"]
    if order_id is None or license_status in {"cancelled", "expired"}:
        return "cancel"
    db.execute(
        text("SELECT set_config('app.outbox_order_id', :order_id, true)"),
        {"order_id": str(order_id)},
    )
    order_status = db.execute(
        text("SELECT status FROM orders WHERE id = :order_id"),
        {"order_id": order_id},
    ).scalar_one_or_none()
    if order_status is None:
        return "cancel"
    if order_status == "pending":
        return "defer"
    if order_status != "paid" or license_status not in {"pending", "active"}:
        return "cancel"
    return "send"


def _process_license_delivery(
    db: Session,
    row_id: uuid.UUID,
    worker_id: uuid.UUID,
    payload: dict[str, str] | None,
    idempotency_key: str,
    attempt_count: int,
    max_attempts: int,
) -> str:
    # Keep the outbox row locked through the provider call. A refund/chargeback
    # cancellation either wins the lock first or waits and sees the final status.
    fresh = db.scalar(
        select(EmailOutbox).where(EmailOutbox.id == row_id).with_for_update()
    )
    if fresh is None or fresh.status != "processing" or fresh.claimed_by != worker_id:
        db.rollback()
        return "cancelled"
    if payload is None:
        fresh.status = "dead"
        fresh.processed_at = _utcnow()
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.last_error = "payload_invalid"
        db.commit()
        return "dead"

    decision = _license_delivery_decision(db, fresh.aggregate_id)
    if decision == "defer":
        fresh.status = "pending"
        fresh.processed_at = _utcnow()
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.next_attempt_at = _utcnow() + timedelta(seconds=_LICENSE_DELIVERY_DEFER_SECONDS)
        fresh.last_error = "license_pending"
        fresh.attempt_count = max(0, fresh.attempt_count - 1)
        db.commit()
        return "pending"
    if decision != "send":
        fresh.status = "cancelled"
        fresh.processed_at = _utcnow()
        fresh.payload_encrypted = None
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.last_error = "license_not_deliverable"
        db.commit()
        return "cancelled"

    try:
        recipient, subject, body = email_service.render_message("license_delivery", payload)
        provider_id = email_service.send_rendered_email(
            recipient, subject, body, idempotency_key=idempotency_key
        )
    except email_service.PermanentEmailDeliveryError:
        fresh.status = "dead"
        fresh.processed_at = _utcnow()
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.last_error = "permanent_failure"
        db.commit()
        return "dead"
    except Exception as exc:
        outcome = "dead" if attempt_count >= max_attempts else "pending"
        if isinstance(exc, email_service.TransientEmailDeliveryError):
            error_code = str(exc) if str(exc) in {"provider_transient", "provider_unavailable"} else "provider_unavailable"
        else:
            error_code = "processing_failure"
        fresh.status = outcome
        fresh.processed_at = _utcnow()
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.last_error = error_code
        if outcome == "pending":
            fresh.next_attempt_at = _utcnow() + timedelta(seconds=_backoff_seconds(attempt_count))
        db.commit()
        return outcome

    fresh.status = "sent"
    fresh.sent_at = _utcnow()
    fresh.processed_at = _utcnow()
    fresh.payload_encrypted = None
    fresh.claimed_by = None
    fresh.lease_until = None
    fresh.provider_message_id = provider_id
    fresh.last_error = None
    db.commit()
    return "sent"


def _process_generic(
    db: Session,
    row_id: uuid.UUID,
    worker_id: uuid.UUID,
    event_type: str,
    idempotency_key: str,
    attempt_count: int,
    max_attempts: int,
) -> str:
    """Process non-license messages while holding the outbox row lock.

    The row is locked before token validation, payload decryption and provider
    I/O. A cancellation transaction therefore either wins before this lock and
    is observed here, or waits until the provider outcome is committed. The
    password reset token is read without a lock to keep the lock order
    compatible with reset_password(), which locks the token before updating the
    outbox.
    """
    fresh = db.scalar(
        select(EmailOutbox).where(EmailOutbox.id == row_id).with_for_update()
    )
    if fresh is None or fresh.status != "processing" or fresh.claimed_by != worker_id:
        db.rollback()
        return "cancelled"

    if fresh.expires_at is not None and fresh.expires_at <= _utcnow():
        fresh.status = "cancelled"
        fresh.processed_at = _utcnow()
        fresh.payload_encrypted = None
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.last_error = "expired"
        db.commit()
        return "cancelled"

    if event_type == "password_reset" and not _password_reset_is_current(db, fresh.aggregate_id):
        fresh.status = "cancelled"
        fresh.processed_at = _utcnow()
        fresh.payload_encrypted = None
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.last_error = "obsolete_reset_token"
        db.commit()
        return "cancelled"

    try:
        payload = _payload(fresh)
    except Exception:
        fresh.status = "dead"
        fresh.processed_at = _utcnow()
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.last_error = "permanent_failure"
        db.commit()
        return "dead"

    try:
        recipient, subject, body = email_service.render_message(event_type, payload)
        provider_id = email_service.send_rendered_email(
            recipient, subject, body, idempotency_key=idempotency_key
        )
    except email_service.PermanentEmailDeliveryError:
        outcome, error_code = "dead", "permanent_failure"
    except Exception as exc:
        outcome = "dead" if attempt_count >= max_attempts else "pending"
        if isinstance(exc, email_service.TransientEmailDeliveryError):
            error_code = str(exc) if str(exc) in {"provider_transient", "provider_unavailable"} else "provider_unavailable"
        else:
            error_code = "processing_failure"
    else:
        fresh.status = "sent"
        fresh.sent_at = _utcnow()
        fresh.processed_at = _utcnow()
        fresh.payload_encrypted = None
        fresh.claimed_by = None
        fresh.lease_until = None
        fresh.provider_message_id = provider_id
        fresh.last_error = None
        db.commit()
        return "sent"

    fresh.status = outcome
    fresh.processed_at = _utcnow()
    fresh.claimed_by = None
    fresh.lease_until = None
    fresh.last_error = error_code
    if outcome == "pending":
        fresh.next_attempt_at = _utcnow() + timedelta(seconds=_backoff_seconds(attempt_count))
    # Retry/dead messages retain only the encrypted payload. A later worker
    # retry revalidates token state before decrypting and sending again.
    db.commit()
    return outcome


def process_one(db: Session, row_id: uuid.UUID, worker_id: uuid.UUID) -> str:
    row = _load_claim(db, row_id, worker_id)
    if row is None:
        return "cancelled"
    event_type = row.event_type
    idempotency_key = row.idempotency_key
    attempt_count, max_attempts = row.attempt_count, row.max_attempts
    if event_type == _LICENSE_DELIVERY:
        try:
            payload = _payload(row)
        except Exception:
            payload = None
        db.rollback()
        return _process_license_delivery(
            db, row_id, worker_id, payload, idempotency_key, attempt_count, max_attempts
        )
    db.rollback()
    return _process_generic(
        db,
        row_id,
        worker_id,
        event_type,
        idempotency_key,
        attempt_count,
        max_attempts,
    )


def requeue_dead(db: Session, event_id: uuid.UUID) -> bool:
    row = db.scalar(
        select(EmailOutbox).where(EmailOutbox.id == event_id).with_for_update()
    )
    if (
        row is None
        or row.status != "dead"
        or row.payload_encrypted is None
        or (row.expires_at is not None and row.expires_at <= _utcnow())
        or row.manual_requeue_count >= 1
    ):
        db.rollback()
        return False
    if row.event_type == "activation_verification":
        # A fresh verification code is required for activation recovery.
        db.rollback()
        return False
    if row.event_type == _LICENSE_DELIVERY and _license_delivery_decision(db, row.aggregate_id) == "cancel":
        # Never reopen a delivery whose license/order is no longer deliverable.
        db.rollback()
        return False
    if row.event_type == "password_reset" and not _password_reset_is_current(db, row.aggregate_id):
        db.rollback()
        return False
    actor = db.execute(text("SELECT current_user")).scalar_one()
    row.status = "pending"
    # Preserve the original attempt budget; one explicit recovery can add only
    # one additional configured budget, and cannot be repeated indefinitely.
    row.max_attempts += settings.OUTBOX_MAX_ATTEMPTS
    row.manual_requeue_count += 1
    row.last_requeued_at = _utcnow()
    row.last_requeued_by = actor
    row.next_attempt_at = _utcnow()
    row.processed_at = None
    row.claimed_by = None
    row.lease_until = None
    row.last_error = None
    db.commit()
    return True


def queue_snapshot(db: Session) -> dict[str, int | float | None]:
    result = db.execute(text("""
        SELECT
          count(*) FILTER (WHERE status = 'pending') AS pending,
          count(*) FILTER (WHERE status = 'processing') AS processing,
          count(*) FILTER (WHERE status = 'processing' AND lease_until <= now()) AS expired_leases,
          count(*) FILTER (WHERE status = 'dead') AS dead,
          extract(epoch FROM (now() - min(created_at) FILTER (WHERE status = 'pending'))) AS oldest_pending_seconds,
          count(*) FILTER (
            WHERE last_error IN ('provider_transient','provider_unavailable')
              AND processed_at >= now() - interval '15 minutes'
          ) AS provider_errors_15m
        FROM email_outbox
    """)).mappings().one()
    return dict(result)


def run_batch(session_factory, worker_id: uuid.UUID, *, batch_size: int | None = None) -> dict[str, int]:
    with session_factory() as db:
        ids = claim_batch(db, worker_id, batch_size=batch_size)
    counts = {"claimed": len(ids), "sent": 0, "pending": 0, "dead": 0, "cancelled": 0}
    for row_id in ids:
        with session_factory() as db:
            result = process_one(db, row_id, worker_id)
        counts[result] = counts.get(result, 0) + 1
    return counts
