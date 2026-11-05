from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import set_db_context
from app.core.field_encryption import (
    decrypt_text,
    email_lookup_hash,
    encrypt_text,
    masked_email,
    normalize_email,
)
from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.core.support_permissions import SUPPORT_GRANTS
from app.models.email_outbox import EmailOutbox
from app.models.license import License
from app.models.order import Order
from app.models.payment_event import PaymentEvent
from app.models.product import Product
from app.models.support import SupportAuditLog, SupportOperator, SupportSession
from app.services import email_outbox_service

settings = get_settings()
_DUMMY_HASH = hash_password("fortexahome-support-dummy-password")
_MAX_FAILURES = 5
_LOCK_MINUTES = 15
_RECOVERY_EVENT = "license_recovery_instructions"
_TERMINAL_ORDERS = {"refunded", "chargeback", "cancelled"}


def _operator_public(operator: SupportOperator) -> dict:
    return {
        "id": operator.id,
        "name": decrypt_text(operator.name_encrypted, "support_operators.name") or "",
        "email": decrypt_text(operator.email_encrypted, "support_operators.email") or "",
        "role": operator.role,
        "status": operator.status,
        "created_at": operator.created_at,
        "last_login_at": operator.last_login_at,
    }


def _permissions(operator: SupportOperator) -> list[str]:
    return sorted(SUPPORT_GRANTS.get(operator.role, frozenset()))


def _audit(
    db: Session,
    operator: SupportOperator,
    operation: str,
    result: str,
    *,
    order_id: uuid.UUID | None = None,
    license_id: uuid.UUID | None = None,
    outbox_id: uuid.UUID | None = None,
    justification: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        SupportAuditLog(
            operator_id=operator.id,
            operation=operation,
            order_id=order_id,
            license_id=license_id,
            outbox_id=outbox_id,
            justification=justification,
            result=result,
            details={"operator_masked": operator.email_masked, **(details or {})},
        )
    )


def authenticate_support(db: Session, *, email: str, password: str) -> tuple[str, dict]:
    email_hash = email_lookup_hash(email)
    set_db_context(db, support_login_email_hash=email_hash)
    operator = db.scalar(
        select(SupportOperator).where(SupportOperator.email_lookup_hash == email_hash)
    )
    if operator is None:
        verify_password(password, _DUMMY_HASH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    now = datetime.now(timezone.utc)
    if operator.locked_until is not None and operator.locked_until > now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    if operator.status != "active":
        verify_password(password, _DUMMY_HASH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    if not verify_password(password, operator.password_hash):
        operator.failed_login_count += 1
        if operator.failed_login_count >= _MAX_FAILURES:
            operator.locked_until = now + timedelta(minutes=_LOCK_MINUTES)
            operator.failed_login_count = 0
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    operator.failed_login_count = 0
    operator.locked_until = None
    operator.last_login_at = now
    set_db_context(db, support_operator_id=operator.id)
    token = generate_token()
    db.add(
        SupportSession(
            operator_id=operator.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(hours=settings.SUPPORT_SESSION_EXPIRE_HOURS),
        )
    )
    _audit(db, operator, "SUPPORT_LOGIN", "success")
    db.commit()
    return token, {"operator": _operator_public(operator), "permissions": _permissions(operator)}


def logout_support(db: Session, operator: SupportOperator, session_id: uuid.UUID) -> None:
    set_db_context(db, support_operator_id=operator.id)
    session = db.get(SupportSession, session_id)
    if session is not None and session.operator_id == operator.id:
        session.revoked_at = datetime.now(timezone.utc)
    _audit(db, operator, "SUPPORT_LOGOUT", "success")
    db.commit()


def support_me(operator: SupportOperator) -> dict:
    return {"operator": _operator_public(operator), "permissions": _permissions(operator)}


def _date_bounds(start: date | None, end: date | None):
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc) if start else None
    end_at = datetime.combine(end, time.max, tzinfo=timezone.utc) if end else None
    return start_at, end_at


def list_orders(
    db: Session,
    *,
    transaction: str | None = None,
    order_status: str | None = None,
    license_status: str | None = None,
    product_slug: str | None = None,
    start: date | None = None,
    end: date | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    latest_delivery = (
        select(EmailOutbox.status)
        .where(
            EmailOutbox.event_type == "license_delivery",
            EmailOutbox.aggregate_id == License.id,
        )
        .order_by(EmailOutbox.created_at.desc())
        .limit(1)
        .correlate(License)
        .scalar_subquery()
    )
    last_event = (
        select(func.max(func.coalesce(PaymentEvent.provider_event_created_at, PaymentEvent.created_at)))
        .where(PaymentEvent.order_id == Order.id)
        .correlate(Order)
        .scalar_subquery()
    )
    filters = []
    if transaction:
        filters.append(Order.external_order_id.ilike(f"%{transaction.strip()}%"))
    if order_status:
        filters.append(Order.status == order_status)
    if license_status:
        filters.append(License.status == license_status)
    if product_slug:
        filters.append(Product.slug == product_slug)
    start_at, end_at = _date_bounds(start, end)
    if start_at:
        filters.append(Order.created_at >= start_at)
    if end_at:
        filters.append(Order.created_at <= end_at)

    base = (
        select(Order, Product, License, latest_delivery, last_event)
        .join(Product, Product.id == Order.product_id)
        .outerjoin(License, License.order_id == Order.id)
        .where(*filters)
        .order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = db.execute(base).all()
    total = db.scalar(
        select(func.count())
        .select_from(Order)
        .join(Product, Product.id == Order.product_id)
        .outerjoin(License, License.order_id == Order.id)
        .where(*filters)
    )
    items = [
        {
            "id": order.id,
            "transaction": order.external_order_id,
            "provider": order.provider,
            "status": order.status,
            "product_slug": product.slug,
            "product_name": product.name,
            "created_at": order.created_at,
            "last_event_at": last_event_at,
            "license_id": license_row.id if license_row else None,
            "license_status": license_row.status if license_row else None,
            "license_code_last4": license_row.code_last4 if license_row else None,
            "delivery_status": delivery_status,
        }
        for order, product, license_row, delivery_status, last_event_at in rows
    ]
    return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}


def _order_query(db: Session, order_id: uuid.UUID):
    return db.execute(
        select(Order, Product, License)
        .join(Product, Product.id == Order.product_id)
        .outerjoin(License, License.order_id == Order.id)
        .where(Order.id == order_id)
    ).one_or_none()


def get_order(db: Session, order_id: uuid.UUID) -> dict:
    row = _order_query(db, order_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado")
    order, product, license_row = row
    buyer_email = decrypt_text(order.buyer_email_encrypted, "orders.buyer_email")
    events = db.scalars(
        select(PaymentEvent)
        .where(PaymentEvent.order_id == order.id)
        .order_by(
            func.coalesce(PaymentEvent.provider_event_created_at, PaymentEvent.created_at),
            PaymentEvent.state_priority,
        )
    ).all()
    deliveries = []
    if license_row is not None:
        deliveries = db.execute(
            select(
                EmailOutbox.id,
                EmailOutbox.event_type,
                EmailOutbox.status,
                EmailOutbox.attempt_count,
                EmailOutbox.max_attempts,
                EmailOutbox.next_attempt_at,
                EmailOutbox.processed_at,
                EmailOutbox.sent_at,
                EmailOutbox.last_error,
                EmailOutbox.created_at,
            )
            .where(EmailOutbox.aggregate_id == license_row.id)
            .order_by(EmailOutbox.created_at.desc())
        ).mappings().all()
    return {
        "order": {
            "id": order.id,
            "transaction": order.external_order_id,
            "provider": order.provider,
            "status": order.status,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "amount_cents": order.amount_cents,
            "currency": order.currency,
            "buyer_email_masked": masked_email(buyer_email) if buyer_email else None,
        },
        "product": {"slug": product.slug, "name": product.name},
        "license": {
            "id": license_row.id,
            "status": license_row.status,
            "code_last4": license_row.code_last4,
            "tenant_id": license_row.tenant_id,
            "issued_at": license_row.issued_at,
            "activated_at": license_row.activated_at,
            "expires_at": license_row.expires_at,
            "revoked_at": license_row.revoked_at,
        }
        if license_row
        else None,
        "events": [
            {
                "event_type": event.event_type,
                "provider_event_created_at": event.provider_event_created_at,
                "processed_at": event.processed_at,
                "state_priority": event.state_priority,
            }
            for event in events
        ],
        "deliveries": [
            {
                "id": delivery["id"],
                "event_type": delivery["event_type"],
                "status": delivery["status"],
                "attempt_count": delivery["attempt_count"],
                "max_attempts": delivery["max_attempts"],
                "next_attempt_at": delivery["next_attempt_at"],
                "processed_at": delivery["processed_at"],
                "sent_at": delivery["sent_at"],
                "last_error": delivery["last_error"],
                "created_at": delivery["created_at"],
            }
            for delivery in deliveries
        ],
    }


def list_licenses(
    db: Session,
    *,
    status_filter: str | None = None,
    product_slug: str | None = None,
    transaction: str | None = None,
    tenant_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    filters = []
    if status_filter:
        filters.append(License.status == status_filter)
    if product_slug:
        filters.append(Product.slug == product_slug)
    if transaction:
        filters.append(Order.external_order_id.ilike(f"%{transaction.strip()}%"))
    if tenant_id:
        filters.append(License.tenant_id == tenant_id)
    base = (
        select(License, Product, Order)
        .join(Product, Product.id == License.product_id)
        .outerjoin(Order, Order.id == License.order_id)
        .where(*filters)
        .order_by(License.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = db.execute(base).all()
    total = db.scalar(
        select(func.count())
        .select_from(License)
        .join(Product, Product.id == License.product_id)
        .outerjoin(Order, Order.id == License.order_id)
        .where(*filters)
    )
    items = [
        {
            "id": license_row.id,
            "code_last4": license_row.code_last4,
            "status": license_row.status,
            "product_slug": product.slug,
            "product_name": product.name,
            "order_id": order.id if order else None,
            "transaction": order.external_order_id if order else None,
            "tenant_id": license_row.tenant_id,
            "issued_at": license_row.issued_at,
            "activated_at": license_row.activated_at,
            "expires_at": license_row.expires_at,
            "revoked_at": license_row.revoked_at,
        }
        for license_row, product, order in rows
    ]
    return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}


def list_outbox(
    db: Session,
    *,
    status_filter: str | None = None,
    event_type: str | None = None,
    aggregate_id: uuid.UUID | None = None,
    transaction: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    filters = []
    if status_filter:
        filters.append(EmailOutbox.status == status_filter)
    if event_type:
        filters.append(EmailOutbox.event_type == event_type)
    if aggregate_id:
        filters.append(EmailOutbox.aggregate_id == aggregate_id)
    if transaction:
        filters.append(Order.external_order_id.ilike(f"%{transaction.strip()}%"))
    base = (
        select(
            EmailOutbox.id.label("outbox_id"),
            EmailOutbox.event_type,
            EmailOutbox.status,
            EmailOutbox.aggregate_id,
            EmailOutbox.attempt_count,
            EmailOutbox.max_attempts,
            EmailOutbox.next_attempt_at,
            EmailOutbox.processed_at,
            EmailOutbox.sent_at,
            EmailOutbox.last_error,
            EmailOutbox.created_at,
            License.id.label("license_id"),
            Order.id.label("order_id"),
            Order.external_order_id.label("transaction"),
            Order.status.label("order_status"),
        )
        .outerjoin(License, License.id == EmailOutbox.aggregate_id)
        .outerjoin(Order, Order.id == License.order_id)
        .where(*filters)
        .order_by(EmailOutbox.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = db.execute(base).mappings().all()
    total = db.scalar(
        select(func.count())
        .select_from(EmailOutbox)
        .outerjoin(License, License.id == EmailOutbox.aggregate_id)
        .outerjoin(Order, Order.id == License.order_id)
        .where(*filters)
    )
    items = [
        {
            "id": row["outbox_id"],
            "event_type": row["event_type"],
            "status": row["status"],
            "aggregate_id": row["aggregate_id"],
            "license_id": row["license_id"],
            "order_id": row["order_id"],
            "transaction": row["transaction"],
            "order_status": row["order_status"],
            "attempt_count": row["attempt_count"],
            "max_attempts": row["max_attempts"],
            "next_attempt_at": row["next_attempt_at"],
            "processed_at": row["processed_at"],
            "sent_at": row["sent_at"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}


def dashboard(db: Session) -> dict:
    order_counts = dict(
        db.execute(select(Order.status, func.count()).group_by(Order.status)).all()
    )
    license_counts = dict(
        db.execute(select(License.status, func.count()).group_by(License.status)).all()
    )
    outbox_counts = dict(
        db.execute(select(EmailOutbox.status, func.count()).group_by(EmailOutbox.status)).all()
    )
    return {
        "orders": {key: int(value) for key, value in order_counts.items()},
        "licenses": {key: int(value) for key, value in license_counts.items()},
        "outbox": {key: int(value) for key, value in outbox_counts.items()},
        "dead_letters": int(outbox_counts.get("dead", 0)),
    }


def resend_recovery_instructions(
    db: Session,
    operator: SupportOperator,
    *,
    order_id: uuid.UUID,
    justification: str,
) -> dict:
    row = _order_query(db, order_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado")
    order, product, license_row = row
    if order.status in _TERMINAL_ORDERS:
        _audit(db, operator, "SUPPORT_RECOVERY_INSTRUCTIONS", "rejected_terminal", order_id=order.id, justification=justification)
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido não permite recuperação")
    if license_row is None or license_row.status in {"cancelled", "expired", "suspended"}:
        _audit(db, operator, "SUPPORT_RECOVERY_INSTRUCTIONS", "rejected_license", order_id=order.id, license_id=license_row.id if license_row else None, justification=justification)
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Licença não permite recuperação")
    buyer_email = decrypt_text(order.buyer_email_encrypted, "orders.buyer_email")
    if not buyer_email:
        _audit(db, operator, "SUPPORT_RECOVERY_INSTRUCTIONS", "rejected_email", order_id=order.id, license_id=license_row.id, justification=justification)
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido sem e-mail de compra")

    now = datetime.now(timezone.utc)
    idempotency_key = f"support-license-recovery:{license_row.id}:{now:%Y%m%d%H}"
    existing = db.scalar(select(EmailOutbox.id).where(EmailOutbox.idempotency_key == idempotency_key))
    if existing is not None:
        _audit(db, operator, "SUPPORT_RECOVERY_INSTRUCTIONS", "rejected_duplicate", order_id=order.id, license_id=license_row.id, outbox_id=existing, justification=justification)
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instruções já solicitadas nesta hora")

    try:
        message = email_outbox_service.enqueue_email(
            db,
            event_type=_RECOVERY_EVENT,
            payload={"to": buyer_email, "product_name": product.name},
            idempotency_key=idempotency_key,
            aggregate_id=license_row.id,
        )
        _audit(db, operator, "SUPPORT_RECOVERY_INSTRUCTIONS", "success", order_id=order.id, license_id=license_row.id, outbox_id=message.id, justification=justification)
        db.commit()
    except IntegrityError:
        db.rollback()
        _audit(db, operator, "SUPPORT_RECOVERY_INSTRUCTIONS", "rejected_duplicate", order_id=order.id, license_id=license_row.id, justification=justification)
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instruções já solicitadas nesta hora") from None
    return {"message": "Instruções de recuperação enfileiradas."}


def list_audit(db: Session, *, page: int = 1, page_size: int = 25) -> dict:
    rows = db.scalars(
        select(SupportAuditLog)
        .order_by(SupportAuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    total = db.scalar(select(func.count()).select_from(SupportAuditLog))
    items = [
        {
            "id": row.id,
            "operator_id": row.operator_id,
            "operator_masked": (row.details or {}).get("operator_masked"),
            "operation": row.operation,
            "order_id": row.order_id,
            "license_id": row.license_id,
            "outbox_id": row.outbox_id,
            "justification": row.justification,
            "result": row.result,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}


def provision_support_operator(
    db: Session,
    *,
    email: str,
    name: str,
    role: str,
    password: str | None,
    active: bool | None,
    apply: bool = True,
) -> dict:
    from app.schemas.support import SupportOperatorProvision

    email_normalized = normalize_email(email)
    email_hash = email_lookup_hash(email_normalized)
    payload = {
        "email": email_normalized,
        "name": name.strip(),
        "role": role,
        "password": password or "placeholder-not-used-for-existing-operator",
        "status": "active" if active is None else ("active" if active else "disabled"),
    }
    validated = SupportOperatorProvision(**payload)
    set_db_context(db, support_provisioning="true", support_login_email_hash=email_hash)
    operator = db.scalar(
        select(SupportOperator).where(SupportOperator.email_lookup_hash == email_hash).with_for_update()
    )
    if operator is None:
        if not password:
            raise ValueError("senha é obrigatória para criar um operador")
        operator = SupportOperator(
            email_encrypted=encrypt_text(email_normalized, "support_operators.email"),
            email_lookup_hash=email_hash,
            email_masked=masked_email(email_normalized),
            name_encrypted=encrypt_text(validated.name, "support_operators.name"),
            password_hash=hash_password(password),
            role=validated.role,
            status=validated.status,
            password_changed_at=datetime.now(timezone.utc) if password else None,
        )
        if not apply:
            return {"action": "would_create", "operator": _operator_public(operator)}
        db.add(operator)
        db.flush()
        return {"action": "created", "operator": _operator_public(operator)}

    changes = []
    if decrypt_text(operator.name_encrypted, "support_operators.name") != validated.name:
        operator.name_encrypted = encrypt_text(validated.name, "support_operators.name")
        changes.append("name")
    if operator.role != validated.role:
        operator.role = validated.role
        changes.append("role")
    if password:
        operator.password_hash = hash_password(password)
        operator.password_changed_at = datetime.now(timezone.utc)
        changes.append("password")
    if active is not None and operator.status != validated.status:
        operator.status = validated.status
        changes.append("status")
    if not changes:
        return {"action": "unchanged", "operator": _operator_public(operator)}
    if not apply:
        return {"action": "would_update", "operator": _operator_public(operator), "changed_fields": changes}
    db.flush()
    return {"action": "updated", "operator": _operator_public(operator), "changed_fields": changes}
