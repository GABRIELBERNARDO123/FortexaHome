from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import set_db_context
from app.core.field_encryption import (
    decrypt_text,
    email_lookup_hash,
    encrypt_text,
    masked_email,
    normalize_email,
)
from app.core.rate_limit import hash_rate_limit_key
from app.core.security import generate_token, hash_password, verify_password
from app.models.audit_log import AuditLog
from app.models.bill import Bill
from app.models.budget import Budget
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.email_outbox import EmailOutbox
from app.models.goal import Goal
from app.models.idempotency import IdempotencyRecord
from app.models.license import License
from app.models.login_lockout import LoginLockoutState
from app.models.order import Order
from app.models.password_reset import PasswordResetToken
from app.models.pending_activation import PendingActivation
from app.models.privacy import DataDeletionTombstone, PrivacyRequest, PrivacyRequestEvent
from app.models.rate_limit import RateLimitBucket
from app.models.session import UserSession
from app.models.subscription import Subscription
from app.models.support import SupportAuditLog, SupportOperator
from app.models.tenant import Tenant
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service, login_lockout_service

_ACTIVE_STATUSES = ("submitted", "awaiting_review", "approved", "processing")
_TERMINAL_STATUSES = ("completed", "partially_completed", "rejected", "cancelled")
_RATE_SCOPES = (
    "auth.login",
    "auth.activate",
    "auth.activate.confirm",
    "auth.activate.resend",
    "auth.recover_license",
    "auth.recover_license.confirm",
    "auth.forgot_password",
    "auth.reset_password",
    "privacy.request",
)

_RETAINED_SUMMARY = {
    "commercial_records": {
        "status": "retained_anonymized",
        "items": ["orders", "payment_events", "licenses"],
        "justification": "comprovação contratual, financeira e de suporte; revisão jurídica/contábil necessária para prazo final",
    },
    "audit_and_security": {
        "status": "retained_anonymized",
        "items": ["audit_logs", "support_audit_logs", "data_deletion_tombstones"],
        "justification": "segurança, auditoria e comprovação da própria exclusão",
    },
    "logs_and_backups": {
        "status": "retained_external",
        "items": ["application_logs", "database_backups"],
        "justification": "prazo e procedimento de expurgo dependem de decisão operacional/jurídica",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _protocol() -> str:
    return f"PRIV-{_now():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"


def _request_public(row: PrivacyRequest) -> dict:
    return {
        "id": row.id,
        "protocol": row.protocol,
        "request_type": row.request_type,
        "status": row.status,
        "scope": row.scope,
        "reason": row.reason,
        "retention_summary": row.retention_summary,
        "result_summary": row.result_summary,
        "review_justification": row.review_justification,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "reviewed_at": row.reviewed_at,
        "completed_at": row.completed_at,
        "cancelled_at": row.cancelled_at,
    }


def _event_public(row: PrivacyRequestEvent) -> dict:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "status": row.status,
        "actor_type": row.actor_type,
        "details": row.details,
        "created_at": row.created_at,
    }


def _event(
    db: Session,
    request: PrivacyRequest,
    event_type: str,
    *,
    status: str | None = None,
    actor_type: str,
    actor_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        PrivacyRequestEvent(
            request_id=request.id,
            tenant_id=request.tenant_id,
            event_type=event_type,
            status=status or request.status,
            actor_type=actor_type,
            actor_id=actor_id,
            details=details,
        )
    )


def _support_audit(
    db: Session,
    operator: SupportOperator,
    request: PrivacyRequest,
    operation: str,
    result: str,
    justification: str | None,
) -> None:
    db.add(
        SupportAuditLog(
            operator_id=operator.id,
            operation=operation,
            result=result,
            justification=justification,
            details={
                "operator_masked": operator.email_masked,
                "privacy_request_id": str(request.id),
                "protocol": request.protocol,
            },
        )
    )


def _cancel_outbox(db: Session, aggregate_ids: list[uuid.UUID]) -> int:
    ids = list({item for item in aggregate_ids if item is not None})
    if not ids:
        return 0
    now = _now()
    set_db_context(db, privacy_erasure="true")
    pending = db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.aggregate_id.in_(ids),
            EmailOutbox.status.in_(("pending", "processing")),
        )
        .values(
            status="cancelled",
            processed_at=now,
            payload_encrypted=None,
            claimed_by=None,
            lease_until=None,
            last_error="privacy_erasure",
        )
    )
    db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.aggregate_id.in_(ids),
            EmailOutbox.status.in_(("dead", "cancelled")),
        )
        .values(payload_encrypted=None, last_error="privacy_erasure")
    )
    return int(pending.rowcount or 0)


def _delete_rate_limits(
    db: Session, *, email: str | None, user_ids: list[uuid.UUID], tenant_id: uuid.UUID | None = None
) -> None:
    hashes: set[str] = set()
    for scope in _RATE_SCOPES:
        if email:
            hashes.add(hash_rate_limit_key(scope, "email", normalize_email(email)))
        for user_id in user_ids:
            hashes.add(hash_rate_limit_key(scope, "user", str(user_id)))
        if tenant_id is not None:
            hashes.add(hash_rate_limit_key(scope, "tenant", str(tenant_id)))
    if hashes:
        db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(hashes)))


def _anonymize_pending_activations(db: Session, activation_ids: list[uuid.UUID]) -> int:
    count = 0
    for activation_id in list({item for item in activation_ids if item is not None}):
        row = db.get(PendingActivation, activation_id)
        if row is None:
            continue
        placeholder = f"deleted-{row.id}@invalid.local"
        row.email_encrypted = encrypt_text(placeholder, "pending_activations.email")
        row.email_lookup_hash = email_lookup_hash(placeholder)
        row.name_encrypted = encrypt_text("Conta excluída", "pending_activations.name")
        row.password_hash = hash_password(generate_token())
        row.verification_code_hash = None
        row.status = "expired"
        count += 1
    return count


def _anonymize_user(db: Session, user: User) -> None:
    email = decrypt_text(user.email_encrypted, "users.email") or ""
    email_hash = user.email_lookup_hash
    sessions = list(db.scalars(select(UserSession.id).where(UserSession.user_id == user.id)).all())
    reset_ids = list(
        db.scalars(select(PasswordResetToken.id).where(PasswordResetToken.user_id == user.id)).all()
    )
    activation_ids = list(
        db.scalars(
            select(PendingActivation.id).where(PendingActivation.email_lookup_hash == email_hash)
        ).all()
    )
    _cancel_outbox(db, [*reset_ids, *activation_ids])
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    _anonymize_pending_activations(db, activation_ids)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id == user.id))
    db.execute(delete(LoginLockoutState).where(LoginLockoutState.key_hash == login_lockout_service.lockout_key(email)))
    _delete_rate_limits(db, email=email, user_ids=[user.id])
    db.execute(update(AuditLog).where(AuditLog.user_id == user.id).values(user_id=None))
    placeholder_email = f"deleted-{user.id}@invalid.local"
    user.email_encrypted = encrypt_text(placeholder_email, "users.email")
    user.email_lookup_hash = email_lookup_hash(placeholder_email)
    user.email_masked = masked_email(placeholder_email)
    user.name_encrypted = encrypt_text("Conta excluída", "users.name")
    user.password_hash = hash_password(generate_token())
    user.password_changed_at = _now()
    user.status = "disabled"
    user.theme = "minimal"
    user.email_verified_at = None
    user.last_login_at = None
    user.failed_login_count = 0
    _ = sessions  # sessions são apagadas; a variável mantém a intenção explícita


def _execute_user_erasure(db: Session, request: PrivacyRequest) -> dict:
    user = db.scalar(select(User).where(User.id == request.user_id).with_for_update())
    if user is None:
        return {"scope": "user", "already_absent": True}
    _anonymize_user(db, user)
    return {
        "scope": "user",
        "anonymized_users": 1,
        "financial_records": "preserved_for_shared_tenant",
    }


def _execute_tenant_erasure(db: Session, request: PrivacyRequest) -> dict:
    tenant = db.scalar(select(Tenant).where(Tenant.id == request.tenant_id).with_for_update())
    if tenant is None:
        return {"scope": "tenant", "already_absent": True}
    users = db.scalars(select(User).where(User.tenant_id == tenant.id).with_for_update()).all()
    other_active = [
        item for item in users if item.status == "active" and item.id != request.user_id
    ]
    if other_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O tenant possui outros usuários ativos. A exclusão exige análise e procedimento manual.",
        )

    license_ids = list(
        db.scalars(select(License.id).where(License.tenant_id == tenant.id)).all()
    )
    reset_ids = list(
        db.scalars(select(PasswordResetToken.id).where(PasswordResetToken.tenant_id == tenant.id)).all()
    )
    activation_hashes = [item.email_lookup_hash for item in users]
    activation_ids = list(
        db.scalars(
            select(PendingActivation.id).where(
                PendingActivation.email_lookup_hash.in_(activation_hashes)
            )
        ).all()
    ) if activation_hashes else []
    _cancel_outbox(db, [*license_ids, *reset_ids, *activation_ids])

    db.execute(delete(Transaction).where(Transaction.tenant_id == tenant.id))
    db.execute(delete(Bill).where(Bill.tenant_id == tenant.id))
    db.execute(delete(Budget).where(Budget.tenant_id == tenant.id))
    db.execute(delete(Goal).where(Goal.tenant_id == tenant.id))
    db.execute(delete(CreditCard).where(CreditCard.tenant_id == tenant.id))
    db.execute(delete(Category).where(Category.tenant_id == tenant.id))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.tenant_id == tenant.id))
    tenant_activation_ids = list(
        db.scalars(
            select(PendingActivation.id).where(PendingActivation.license_id.in_(license_ids))
        ).all()
    ) if license_ids else []
    _anonymize_pending_activations(db, tenant_activation_ids)
    db.execute(delete(UserSession).where(UserSession.tenant_id == tenant.id))
    db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.tenant_id == tenant.id))
    db.execute(update(Subscription).where(Subscription.tenant_id == tenant.id).values(status="cancelled"))
    db.execute(update(AuditLog).where(AuditLog.tenant_id == tenant.id).values(user_id=None))

    set_db_context(db, privacy_erasure="true")
    db.execute(
        update(License)
        .where(License.tenant_id == tenant.id)
        .values(
            status="cancelled",
            revoked_at=_now(),
            tenant_id=None,
            bound_email_hash=None,
        )
    )
    db.execute(
        update(Order)
        .where(
            Order.id.in_(
                select(License.order_id).where(License.id.in_(license_ids), License.order_id.is_not(None))
            )
        )
        .values(buyer_email_encrypted=None, buyer_email_hash=None, external_customer_id=None)
    )

    for user in users:
        _anonymize_user(db, user)
    tenant.name = "Conta encerrada"
    return {
        "scope": "tenant",
        "anonymized_users": len(users),
        "financial_records": "deleted",
        "commercial_records": "retained_anonymized",
    }


def _execute_request(
    db: Session,
    request: PrivacyRequest,
    *,
    actor_type: str,
    actor_id: uuid.UUID | None,
    operator: SupportOperator | None = None,
    justification: str | None = None,
) -> PrivacyRequest:
    if request.status in _TERMINAL_STATUSES:
        return request
    request.status = "processing"
    _event(db, request, "processing_started", actor_type=actor_type, actor_id=actor_id)

    if request.request_type != "erasure":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este tipo de solicitação exige tratamento manual pelo suporte.",
        )

    result = (
        _execute_tenant_erasure(db, request)
        if request.scope == "tenant"
        else _execute_user_erasure(db, request)
    )
    request.status = "completed"
    request.completed_at = _now()
    request.result_summary = (
        "Dados pessoais anonimizados; registros comerciais e de auditoria preservados de forma anonimizada."
        if result.get("scope") == "tenant"
        else "Dados pessoais do usuário anonimizados; dados financeiros compartilhados do tenant preservados."
    )
    if operator is not None:
        request.reviewed_by = operator.id
        request.reviewed_at = _now()
        request.review_justification = justification
        _support_audit(db, operator, request, "SUPPORT_PRIVACY_APPROVE", "success", justification)
    _event(
        db,
        request,
        "completed",
        actor_type=actor_type,
        actor_id=actor_id,
        details={key: value for key, value in result.items()},
    )
    db.add(
        DataDeletionTombstone(
            request_id=request.id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            scope=request.scope,
            applied_at=request.completed_at,
        )
    )
    audit_service.record(
        db,
        "PRIVACY_ERASURE_COMPLETED",
        tenant_id=request.tenant_id,
        user_id=None,
        entity="privacy_request",
        entity_id=request.id,
        details={"scope": request.scope},
    )
    return request


def create_erasure_request(
    db: Session, *, user: User, password: str, reason: str | None = None
) -> dict:
    locked = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if locked is None or locked.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta indisponível")
    if not verify_password(password, locked.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta")

    existing = db.scalar(
        select(PrivacyRequest)
        .where(
            PrivacyRequest.tenant_id == locked.tenant_id,
            PrivacyRequest.user_id == locked.id,
            PrivacyRequest.request_type == "erasure",
            PrivacyRequest.status.in_(_ACTIVE_STATUSES),
        )
        .with_for_update()
    )
    if existing is not None:
        return _request_public(existing)

    other_active = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.tenant_id == locked.tenant_id,
            User.id != locked.id,
            User.status == "active",
        )
    )
    scope = "tenant" if locked.role == "owner" else "user"
    request = PrivacyRequest(
        tenant_id=locked.tenant_id,
        user_id=locked.id,
        protocol=_protocol(),
        request_type="erasure",
        status="submitted",
        scope=scope,
        reason=(reason or "").strip() or None,
        verification_method="password",
        retention_summary=_RETAINED_SUMMARY,
    )
    db.add(request)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(PrivacyRequest).where(
                PrivacyRequest.tenant_id == locked.tenant_id,
                PrivacyRequest.user_id == locked.id,
                PrivacyRequest.request_type == "erasure",
                PrivacyRequest.status.in_(_ACTIVE_STATUSES),
            )
        )
        if existing is not None:
            return _request_public(existing)
        raise
    _event(db, request, "requested", actor_type="user", actor_id=locked.id)
    audit_service.record(
        db,
        "PRIVACY_REQUEST_CREATED",
        tenant_id=request.tenant_id,
        user_id=locked.id,
        entity="privacy_request",
        entity_id=request.id,
        details={"request_type": request.request_type, "scope": request.scope},
    )

    if scope == "tenant" and int(other_active or 0) > 0:
        request.status = "awaiting_review"
        _event(
            db,
            request,
            "awaiting_review",
            actor_type="system",
            details={"reason": "owner_with_active_members"},
        )
        db.commit()
        return _request_public(request)

    _execute_request(db, request, actor_type="user", actor_id=locked.id)
    db.commit()
    return _request_public(request)


def list_user_requests(db: Session, user: User) -> list[dict]:
    rows = db.scalars(
        select(PrivacyRequest)
        .where(PrivacyRequest.tenant_id == user.tenant_id, PrivacyRequest.user_id == user.id)
        .order_by(PrivacyRequest.created_at.desc())
    ).all()
    return [_request_public(row) for row in rows]


def get_user_request(db: Session, user: User, request_id: uuid.UUID) -> dict:
    row = db.scalar(
        select(PrivacyRequest).where(
            PrivacyRequest.id == request_id,
            PrivacyRequest.tenant_id == user.tenant_id,
            PrivacyRequest.user_id == user.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação não encontrada")
    events = db.scalars(
        select(PrivacyRequestEvent)
        .where(PrivacyRequestEvent.request_id == row.id)
        .order_by(PrivacyRequestEvent.created_at)
    ).all()
    return {**_request_public(row), "events": [_event_public(item) for item in events]}


def cancel_user_request(db: Session, user: User, request_id: uuid.UUID) -> dict:
    row = db.scalar(
        select(PrivacyRequest)
        .where(
            PrivacyRequest.id == request_id,
            PrivacyRequest.tenant_id == user.tenant_id,
            PrivacyRequest.user_id == user.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação não encontrada")
    if row.status not in {"submitted", "awaiting_review"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Solicitação não pode ser cancelada")
    row.status = "cancelled"
    row.cancelled_at = _now()
    _event(db, row, "cancelled", actor_type="user", actor_id=user.id)
    db.commit()
    return _request_public(row)


def list_support_requests(
    db: Session,
    *,
    status_filter: str | None = None,
    request_type: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    filters = []
    if status_filter:
        filters.append(PrivacyRequest.status == status_filter)
    if request_type:
        filters.append(PrivacyRequest.request_type == request_type)
    rows = db.scalars(
        select(PrivacyRequest)
        .where(*filters)
        .order_by(PrivacyRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    total = db.scalar(select(func.count()).select_from(PrivacyRequest).where(*filters))
    return {
        "items": [
            {
                **_request_public(row),
                "user_masked": None,
            }
            for row in rows
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


def get_support_request(db: Session, request_id: uuid.UUID) -> dict:
    row = db.scalar(select(PrivacyRequest).where(PrivacyRequest.id == request_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação não encontrada")
    events = db.scalars(
        select(PrivacyRequestEvent)
        .where(PrivacyRequestEvent.request_id == row.id)
        .order_by(PrivacyRequestEvent.created_at)
    ).all()
    return {**_request_public(row), "events": [_event_public(item) for item in events]}


def support_approve(
    db: Session,
    operator: SupportOperator,
    *,
    request_id: uuid.UUID,
    justification: str,
) -> dict:
    row = db.scalar(
        select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação não encontrada")
    if row.status in _TERMINAL_STATUSES:
        return _request_public(row)
    if row.status not in {"submitted", "awaiting_review", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Solicitação não está apta para aprovação")
    row.status = "approved"
    row.review_justification = justification
    row.reviewed_by = operator.id
    row.reviewed_at = _now()
    _event(db, row, "approved", actor_type="support", actor_id=operator.id)
    set_db_context(db, tenant_id=row.tenant_id)
    try:
        _execute_request(
            db,
            row,
            actor_type="support",
            actor_id=operator.id,
            operator=operator,
            justification=justification,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return _request_public(row)


def support_reject(
    db: Session,
    operator: SupportOperator,
    *,
    request_id: uuid.UUID,
    justification: str,
) -> dict:
    row = db.scalar(
        select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação não encontrada")
    if row.status == "rejected":
        return _request_public(row)
    if row.status in _TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Solicitação já concluída")
    row.status = "rejected"
    row.review_justification = justification
    row.reviewed_by = operator.id
    row.reviewed_at = _now()
    _event(db, row, "rejected", actor_type="support", actor_id=operator.id)
    _support_audit(db, operator, row, "SUPPORT_PRIVACY_REJECT", "rejected", justification)
    db.commit()
    return _request_public(row)


def reapply_tombstone(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID | None, scope: str) -> None:
    """Reapply an exported deletion tombstone after a disposable restore."""
    set_db_context(db, tenant_id=tenant_id)
    request = PrivacyRequest(
        tenant_id=tenant_id,
        user_id=user_id,
        protocol=_protocol(),
        request_type="erasure",
        status="processing",
        scope=scope,
        verification_method="restore_reapply",
        retention_summary=_RETAINED_SUMMARY,
        reason="Reaplicação de exclusão após restauração de backup",
    )
    db.add(request)
    db.flush()
    _execute_request(db, request, actor_type="system", actor_id=None)
    db.commit()


__all__ = [
    "cancel_user_request",
    "create_erasure_request",
    "get_support_request",
    "get_user_request",
    "list_support_requests",
    "list_user_requests",
    "reapply_tombstone",
    "support_approve",
    "support_reject",
]
