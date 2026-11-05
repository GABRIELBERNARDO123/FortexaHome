from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from math import ceil

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import set_db_context
from app.core.email_verification import generate_verification_code, verification_code_hash, verify_code
from app.core.field_encryption import (
    decrypt_text,
    email_lookup_hash,
    encrypt_text,
    masked_email,
    normalize_email,
)
from app.core.security import hash_password, verify_password
from app.models.pending_activation import PendingActivation
from app.models.license import License
from app.models.order import Order
from app.models.tenant import Tenant
from app.models.user import User
from app.services import audit_service, auth_service, email_outbox_service, license_service

CODE_TTL = timedelta(minutes=10)
RESEND_INTERVAL = timedelta(seconds=60)
MAX_ATTEMPTS = 5
GENERIC_ERROR = "Não foi possível concluir a ativação. Confira os dados ou solicite um novo código."


def _public_activation(activation: PendingActivation, email: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "activation_id": activation.id,
        "email_masked": masked_email(email),
        "expires_at": activation.expires_at,
        "resend_at": activation.last_sent_at + RESEND_INTERVAL if activation.last_sent_at else now,
    }


def _retry_after(allowed_at: datetime, now: datetime) -> int:
    return max(1, ceil((allowed_at - now).total_seconds()))


def _generate_code_not_equal_to(activation_id: uuid.UUID, previous_hash: str | None) -> tuple[str, str]:
    while True:
        code = generate_verification_code()
        code_hash = verification_code_hash(activation_id, code)
        if code_hash != previous_hash:
            return code, code_hash


def _upsert_pending_activation(
    db: Session,
    license_row: License,
    *,
    normalized_email: str,
    email_hash: str,
    name: str,
    password: str,
) -> PendingActivation:
    activation = db.scalar(
        select(PendingActivation)
        .where(PendingActivation.license_id == license_row.id)
        .order_by(PendingActivation.created_at.desc())
    )
    previous_code_hash = None
    if activation is None:
        activation = PendingActivation(
            id=uuid.uuid4(),
            license_id=license_row.id,
            license_code_hash=license_row.code_hash,
            email_encrypted=encrypt_text(normalized_email, "pending_activations.email"),
            email_lookup_hash=email_hash,
            name_encrypted=encrypt_text(name, "pending_activations.name"),
            password_hash=hash_password(password),
            attempt_count=0,
            status="pending",
        )
        db.add(activation)
    else:
        set_db_context(db, pending_activation_id=activation.id)
        activation = db.scalar(
            select(PendingActivation)
            .where(PendingActivation.id == activation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if activation is None:
            raise HTTPException(status_code=400, detail=GENERIC_ERROR)
        now = datetime.now(timezone.utc)
        previous_code_hash = activation.verification_code_hash
        same_request = (
            activation.status == "pending"
            and activation.email_lookup_hash == email_hash
            and decrypt_text(activation.name_encrypted, "pending_activations.name") == name
            and verify_password(password, activation.password_hash)
        )
        if not same_request:
            allowed_at = activation.last_sent_at + RESEND_INTERVAL if activation.last_sent_at else now
            if now < allowed_at:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Aguarde antes de solicitar outro código.",
                    headers={"Retry-After": str(_retry_after(allowed_at, now))},
                )
            email_outbox_service.cancel_activation_emails(db, activation.id)
            activation.license_code_hash = license_row.code_hash
            activation.email_encrypted = encrypt_text(normalized_email, "pending_activations.email")
            activation.email_lookup_hash = email_hash
            activation.name_encrypted = encrypt_text(name, "pending_activations.name")
            activation.password_hash = hash_password(password)
            activation.verification_code_hash = None
            activation.expires_at = None
            activation.attempt_count = 0
            activation.status = "pending"
            activation.consumed_at = None
    now = datetime.now(timezone.utc)

    db.flush()
    set_db_context(db, pending_activation_id=activation.id)
    can_send = activation.last_sent_at is None or now >= activation.last_sent_at + RESEND_INTERVAL
    code = None
    if can_send:
        code, activation.verification_code_hash = _generate_code_not_equal_to(
            activation.id, previous_code_hash
        )
        activation.expires_at = now + CODE_TTL
        activation.last_sent_at = now
        activation.attempt_count = 0
        email_outbox_service.enqueue_email(
            db,
            event_type="activation_verification",
            payload={"to": normalized_email, "code": code},
            idempotency_key=f"activation-verification:{activation.id}:{uuid.uuid4()}",
            aggregate_id=activation.id,
            expires_at=activation.expires_at,
        )
    return activation


def start_activation(
    db: Session,
    *,
    name: str,
    email: str,
    password: str,
    license_code: str,
) -> dict:
    normalized_email = normalize_email(email)
    email_hash = email_lookup_hash(normalized_email)
    name = name.strip()
    set_db_context(db, login_email_hash=email_hash)

    try:
        license_row = license_service.validate_license_for_activation(
            db, license_code, email_hash=email_hash
        )
        existing_user = db.scalar(select(User).where(User.email_lookup_hash == email_hash))
        if existing_user is not None:
            raise HTTPException(status_code=400, detail=GENERIC_ERROR)
        activation = _upsert_pending_activation(
            db,
            license_row,
            normalized_email=normalized_email,
            email_hash=email_hash,
            name=name,
            password=password,
        )
        db.commit()
    except HTTPException as exc:
        db.rollback()
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise
        raise HTTPException(status_code=400, detail=GENERIC_ERROR) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=GENERIC_ERROR) from None

    return _public_activation(activation, normalized_email)


def resend_activation(db: Session, activation_id: uuid.UUID) -> dict:
    set_db_context(db, pending_activation_id=activation_id)
    activation = db.scalar(
        select(PendingActivation)
        .where(PendingActivation.id == activation_id)
        .with_for_update()
    )
    if activation is None or activation.status != "pending":
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)

    now = datetime.now(timezone.utc)
    allowed_at = activation.last_sent_at + RESEND_INTERVAL if activation.last_sent_at else now
    if now < allowed_at:
        retry_after = max(1, int((allowed_at - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Aguarde antes de solicitar outro código.",
            headers={"Retry-After": str(retry_after)},
        )

    email = decrypt_text(activation.email_encrypted, "pending_activations.email") or ""
    code, activation.verification_code_hash = _generate_code_not_equal_to(
        activation.id, activation.verification_code_hash
    )
    activation.expires_at = now + CODE_TTL
    activation.last_sent_at = now
    activation.attempt_count = 0
    email_outbox_service.cancel_activation_emails(db, activation.id)
    email_outbox_service.enqueue_email(
        db,
        event_type="activation_verification",
        payload={"to": email, "code": code},
        idempotency_key=f"activation-verification:{activation.id}:{uuid.uuid4()}",
        aggregate_id=activation.id,
        expires_at=activation.expires_at,
    )
    db.commit()
    return _public_activation(activation, email)


def confirm_activation(db: Session, activation_id: uuid.UUID, code: str) -> tuple[str, dict]:
    set_db_context(db, pending_activation_id=activation_id)
    initial_activation = db.scalar(
        select(PendingActivation)
        .where(PendingActivation.id == activation_id)
    )
    if initial_activation is None:
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)

    initial_license_id = initial_activation.license_id
    initial_license_code_hash = initial_activation.license_code_hash
    set_db_context(db, license_code_hash=initial_license_code_hash)
    license_row = db.scalar(
        select(License)
        .where(
            License.id == initial_license_id,
            License.code_hash == initial_license_code_hash,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if license_row is None:
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)

    # Every flow that takes both locks acquires the license first. Refresh the
    # activation after acquiring its lock because the first read was unlocked.
    activation = db.scalar(
        select(PendingActivation)
        .where(PendingActivation.id == activation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        activation is None
        or activation.status != "pending"
        or activation.license_id != initial_license_id
        or activation.license_code_hash != initial_license_code_hash
    ):
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)

    set_db_context(db, login_email_hash=activation.email_lookup_hash)
    # Recheck license state, expiry, and its bound email after both rows are
    # locked. The license lock is already held, so this second SELECT cannot
    # invert the lock order.
    license_row = license_service.validate_license_for_activation_hash(
        db,
        activation.license_id,
        activation.license_code_hash,
        email_hash=activation.email_lookup_hash,
    )
    if activation.attempt_count >= MAX_ATTEMPTS:
        activation.status = "locked"
        activation.verification_code_hash = None
        email_outbox_service.cancel_activation_emails(db, activation.id)
        db.commit()
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)

    now = datetime.now(timezone.utc)
    if activation.expires_at is not None and activation.expires_at <= now:
        activation.status = "expired"
        activation.verification_code_hash = None
        email_outbox_service.cancel_activation_emails(db, activation.id)
        db.commit()
        raise HTTPException(status_code=410, detail=GENERIC_ERROR)
    if activation.verification_code_hash is None or activation.expires_at is None:
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)
    if not verify_code(activation.id, code, activation.verification_code_hash):
        activation.attempt_count += 1
        if activation.attempt_count >= MAX_ATTEMPTS:
            activation.status = "locked"
            activation.verification_code_hash = None
            email_outbox_service.cancel_activation_emails(db, activation.id)
        db.commit()
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)

    email = normalize_email(
        decrypt_text(activation.email_encrypted, "pending_activations.email") or ""
    )
    email_hash = activation.email_lookup_hash
    set_db_context(db, login_email_hash=email_hash, license_code_hash=activation.license_code_hash)
    try:
        if db.scalar(select(User).where(User.email_lookup_hash == email_hash)) is not None:
            activation.status = "expired"
            activation.verification_code_hash = None
            email_outbox_service.cancel_activation_emails(db, activation.id)
            db.commit()
            raise HTTPException(status_code=409, detail=GENERIC_ERROR)

        tenant_id = uuid.uuid4()
        name = decrypt_text(activation.name_encrypted, "pending_activations.name") or ""
        set_db_context(db, tenant_id=tenant_id)
        tenant = Tenant(id=tenant_id, name=name, currency="BRL", timezone="America/Sao_Paulo")
        db.add(tenant)
        db.flush()

        user = User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(email, "users.email"),
            email_lookup_hash=email_hash,
            email_masked=masked_email(email),
            name_encrypted=encrypt_text(name, "users.name"),
            password_hash=activation.password_hash,
            role="owner",
            status="active",
            theme="claro",
            email_verified_at=now,
        )
        db.add(user)
        db.flush()
        auth_service._seed_categories(db, tenant_id)
        license_service.bind_license(db, license_row, tenant_id, email_hash)
        token, _session = auth_service._create_session(db, user)
        audit_service.record(
            db,
            "ACCOUNT_ACTIVATED",
            tenant_id=tenant_id,
            user_id=user.id,
            entity="license",
            entity_id=license_row.id,
        )
        activation.status = "consumed"
        activation.consumed_at = now
        activation.verification_code_hash = None
        email_outbox_service.cancel_activation_emails(db, activation.id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=GENERIC_ERROR) from None
    except Exception:
        db.rollback()
        raise
    return token, auth_service.auth_payload(db, user, tenant, license_row)

RECOVERY_MESSAGE = (
    "Se houver um acesso pendente para este e-mail, enviaremos instruções. "
    "Se a conta já existe, use a recuperação de senha."
)


def _find_recovery_license(db: Session, email_hash: str) -> License | None:
    settings = get_settings()
    providers: list[str] = []
    for provider in ("hotmart", settings.PAYMENT_PROVIDER):
        if provider and provider not in providers:
            providers.append(provider)
    candidates: list[tuple[datetime, License, str, uuid.UUID]] = []
    for provider in providers:
        set_db_context(
            db,
            payment_provider=provider,
            license_recovery_email_hash=email_hash,
        )
        orders = db.scalars(
            select(Order)
            .where(
                Order.provider == provider,
                Order.buyer_email_hash == email_hash,
            )
            .order_by(Order.created_at.desc())
        ).all()
        for order in orders:
            if order.status != "paid":
                continue
            set_db_context(db, payment_provider=provider, payment_order_id=order.id)
            license_row = db.scalar(select(License).where(License.order_id == order.id))
            if license_row is None:
                continue
            try:
                valid = license_service.validate_license_for_activation_hash(
                    db,
                    license_row.id,
                    license_row.code_hash,
                    email_hash=email_hash,
                )
            except HTTPException:
                continue
            candidates.append((order.created_at, valid, provider, order.id))
    if not candidates:
        return None
    _, chosen, provider, order_id = max(candidates, key=lambda item: item[0])
    set_db_context(
        db,
        login_email_hash=email_hash,
        payment_provider=provider,
        payment_order_id=order_id,
        license_code_hash=chosen.code_hash,
    )
    return chosen


def start_license_recovery(db: Session, *, name: str, email: str, password: str) -> dict:
    normalized_email = normalize_email(email)
    email_hash = email_lookup_hash(normalized_email)
    name = name.strip()
    set_db_context(db, login_email_hash=email_hash)
    now = datetime.now(timezone.utc)

    existing_user = db.scalar(select(User).where(User.email_lookup_hash == email_hash))
    if existing_user is not None:
        auth_service.forgot_password(db, email=normalized_email, enforce_cooldown=True)
        audit_service.record(
            db,
            "LICENSE_RECOVERY_REQUESTED",
            details={"channel": "password_reset"},
        )
        db.commit()
        return {"message": RECOVERY_MESSAGE}

    set_db_context(db, pending_recovery_email_hash=email_hash)
    recent = db.scalar(
        select(PendingActivation.id)
        .where(
            PendingActivation.email_lookup_hash == email_hash,
            PendingActivation.last_sent_at.is_not(None),
            PendingActivation.last_sent_at >= now - RESEND_INTERVAL,
        )
        .limit(1)
    )
    if recent is not None:
        audit_service.record(
            db,
            "LICENSE_RECOVERY_REQUESTED",
            details={"channel": "throttled"},
        )
        db.commit()
        return {"message": RECOVERY_MESSAGE}

    license_row = _find_recovery_license(db, email_hash)
    if license_row is None:
        audit_service.record(
            db,
            "LICENSE_RECOVERY_REQUESTED",
            details={"channel": "none"},
        )
        db.commit()
        return {"message": RECOVERY_MESSAGE}

    try:
        activation = _upsert_pending_activation(
            db,
            license_row,
            normalized_email=normalized_email,
            email_hash=email_hash,
            name=name,
            password=password,
        )
        audit_service.record(
            db,
            "LICENSE_RECOVERY_REQUESTED",
            details={"channel": "activation", "license_id": str(license_row.id)},
        )
        db.commit()
    except HTTPException:
        db.rollback()
        audit_service.record(
            db,
            "LICENSE_RECOVERY_REQUESTED",
            details={"channel": "throttled"},
        )
        db.commit()
        return {"message": RECOVERY_MESSAGE}
    except IntegrityError:
        db.rollback()
        return {"message": RECOVERY_MESSAGE}
    return {"message": RECOVERY_MESSAGE}


def confirm_license_recovery(db: Session, *, email: str, code: str) -> tuple[str, dict]:
    normalized_email = normalize_email(email)
    email_hash = email_lookup_hash(normalized_email)
    set_db_context(db, pending_recovery_email_hash=email_hash)
    activation_id = db.scalar(
        select(PendingActivation.id)
        .where(
            PendingActivation.email_lookup_hash == email_hash,
            PendingActivation.status == "pending",
        )
        .order_by(PendingActivation.created_at.desc())
        .limit(1)
    )
    if activation_id is None:
        raise HTTPException(status_code=400, detail=GENERIC_ERROR)
    try:
        token, data = confirm_activation(db, activation_id, code)
    except HTTPException:
        raise HTTPException(status_code=400, detail=GENERIC_ERROR) from None
    audit_service.record(
        db,
        "LICENSE_RECOVERY_CONFIRMED",
        tenant_id=uuid.UUID(str(data["tenant"]["id"])),
        details={"license_id": str(data["license"]["id"])},
    )
    db.commit()
    return token, data

