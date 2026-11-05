from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
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
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.models.category import Category
from app.models.email_outbox import EmailOutbox
from app.models.license import License
from app.models.password_reset import PasswordResetToken
from app.models.product import Product
from app.models.session import UserSession
from app.models.tenant import Tenant
from app.models.user import User
from app.services import audit_service, email_outbox_service, license_service, login_lockout_service

settings = get_settings()
_DUMMY_HASH = hash_password("fortexahome-dummy-password")

DEFAULT_CATEGORIES = [
    ("Moradia", "expense", "#ffa400", "home"),
    ("Alimentação", "expense", "#f29a00", "utensils"),
    ("Transporte", "expense", "#c97d00", "car"),
    ("Saúde", "expense", "#6cc58a", "heart"),
    ("Educação", "expense", "#72b4e6", "book"),
    ("Lazer", "expense", "#ffb733", "gamepad"),
    ("Contas básicas", "expense", "#a06500", "receipt"),
    ("Compras", "expense", "#ff6b5e", "shopping-bag"),
    ("Pets", "expense", "#8d8574", "paw"),
    ("Salário", "income", "#6cc58a", "wallet"),
    ("Renda extra", "income", "#72b4e6", "trending-up"),
    ("Investimentos", "income", "#ffa400", "piggy-bank"),
    ("Outros", "income", "#8d8574", "tag"),
    ("Outros", "expense", "#8d8574", "tag"),
]


def _user_public(user: User) -> dict:
    return {
        "id": user.id,
        "name": decrypt_text(user.name_encrypted, "users.name") or "",
        "email": decrypt_text(user.email_encrypted, "users.email") or "",
        "role": user.role,
        "theme": user.theme,
        "created_at": user.created_at,
    }


def _tenant_public(tenant: Tenant) -> dict:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "currency": tenant.currency,
        "timezone": tenant.timezone,
    }


def _license_public(db: Session, license_row: License) -> dict:
    product = db.get(Product, license_row.product_id)
    return {
        "id": license_row.id,
        "status": license_row.status,
        "code_last4": license_row.code_last4,
        "kind": product.license_kind if product else "lifetime",
        "activated_at": license_row.activated_at,
        "expires_at": license_row.expires_at,
    }


def auth_payload(db: Session, user: User, tenant: Tenant, license_row: License) -> dict:
    return {
        "user": _user_public(user),
        "tenant": _tenant_public(tenant),
        "license": _license_public(db, license_row),
    }


def _create_session(db: Session, user: User) -> tuple[str, UserSession]:
    token = generate_token()
    session = UserSession(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.SESSION_EXPIRE_HOURS),
    )
    db.add(session)
    db.flush()
    return token, session


def _seed_categories(db: Session, tenant_id: uuid.UUID) -> None:
    for name, kind, color, icon in DEFAULT_CATEGORIES:
        db.add(
            Category(
                tenant_id=tenant_id,
                name=name,
                kind=kind,
                color=color,
                icon=icon,
                is_system=True,
            )
        )


def _lockout_error(lockout) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Muitas tentativas de login. Tente novamente mais tarde.",
        headers={"Retry-After": str(max(1, lockout.retry_after_seconds))},
    )


def authenticate(db: Session, *, email: str, password: str) -> tuple[str, dict]:
    email_hash = email_lookup_hash(email)
    lockout = login_lockout_service.get_status(db, email)
    if not lockout.allowed:
        raise _lockout_error(lockout)

    set_db_context(db, login_email_hash=email_hash)
    user = db.scalar(select(User).where(User.email_lookup_hash == email_hash))
    if user is None:
        db.rollback()
        verify_password(password, _DUMMY_HASH)
        lockout = login_lockout_service.record_failure(db, email)
        audit_service.record(db, "LOGIN_FAILED")
        if lockout.lock_triggered:
            audit_service.record(db, "LOGIN_LOCKED")
        db.commit()
        if not lockout.allowed:
            raise _lockout_error(lockout)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    user_id = user.id
    tenant_id = user.tenant_id
    password_hash = user.password_hash
    email_verified = user.email_verified_at is not None
    db.rollback()

    if not verify_password(password, password_hash):
        set_db_context(db, login_email_hash=email_hash, tenant_id=tenant_id)
        current_user = db.get(User, user_id)
        if current_user is not None:
            current_user.failed_login_count += 1
        lockout = login_lockout_service.record_failure(db, email)
        audit_service.record(db, "LOGIN_FAILED", tenant_id=tenant_id, user_id=user_id)
        if lockout.lock_triggered:
            audit_service.record(db, "LOGIN_LOCKED", tenant_id=tenant_id, user_id=user_id)
        db.commit()
        if not lockout.allowed:
            raise _lockout_error(lockout)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    if not email_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    login_lockout_service.record_success(db, email)
    set_db_context(db, login_email_hash=email_hash, tenant_id=tenant_id)
    user = db.get(User, user_id)
    if user is None or user.password_hash != password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    set_db_context(db, tenant_id=tenant_id)
    tenant = db.get(Tenant, tenant_id)
    license_row = license_service.get_license_for_tenant(db, tenant_id)
    now = datetime.now(timezone.utc)

    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada")
    if tenant is None or license_row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Licença não encontrada para esta conta")
    expired = license_row.expires_at is not None and license_row.expires_at <= now
    if license_row.status != "active" or expired:
        license_row.status = "expired" if expired and license_row.status == "active" else license_row.status
        audit_service.record(db, "LOGIN_BLOCKED_LICENSE", tenant_id=user.tenant_id, user_id=user.id)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Licença inativa. Regularize o acesso para continuar",
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = now
    user.failed_login_count = 0
    token, _session = _create_session(db, user)
    audit_service.record(db, "LOGIN_SUCCESS", tenant_id=user.tenant_id, user_id=user.id)
    db.commit()

    return token, auth_payload(db, user, tenant, license_row)


def logout(db: Session, session_id: uuid.UUID, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    set_db_context(db, tenant_id=tenant_id)
    session = db.get(UserSession, session_id)
    if session is not None and session.user_id == user_id:
        session.revoked_at = datetime.now(timezone.utc)
    audit_service.record(db, "LOGOUT", tenant_id=tenant_id, user_id=user_id)
    db.commit()


def me_payload(db: Session, user: User, license_row: License) -> dict:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada")
    return auth_payload(db, user, tenant, license_row)


def forgot_password(db: Session, *, email: str, enforce_cooldown: bool = False) -> str | None:
    email_hash = email_lookup_hash(email)
    set_db_context(db, login_email_hash=email_hash)
    user_lookup = db.scalar(select(User).where(User.email_lookup_hash == email_hash))
    if user_lookup is None:
        return None

    set_db_context(db, tenant_id=user_lookup.tenant_id)
    user = db.scalar(select(User).where(User.id == user_lookup.id).with_for_update())
    if user is None:
        return None
    now = datetime.now(timezone.utc)
    if enforce_cooldown:
        recent = db.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id)
            .order_by(PasswordResetToken.created_at.desc())
            .limit(1)
        )
        if recent is not None and recent.created_at > now - timedelta(seconds=60):
            return None
    previous_reset_ids = list(
        db.scalars(
            select(PasswordResetToken.id).where(PasswordResetToken.user_id == user.id)
        ).all()
    )
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    for reset_id in previous_reset_ids:
        set_db_context(db, password_reset_token_id=reset_id)
        db.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.event_type == "password_reset",
                EmailOutbox.aggregate_id == reset_id,
                EmailOutbox.status.in_(("pending", "processing")),
            )
            .values(
                status="cancelled", processed_at=now, payload_encrypted=None,
                claimed_by=None, lease_until=None, last_error="reset_token_replaced",
            )
        )
    token = generate_token()
    token_hash = hash_token(token)
    reset_row = PasswordResetToken(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES),
    )
    db.add(reset_row)
    db.flush()
    email_normalized = decrypt_text(user.email_encrypted, "users.email") or ""
    email_outbox_service.enqueue_email(
        db,
        event_type="password_reset",
        payload={"to": email_normalized, "token": token},
        idempotency_key=f"password-reset:{reset_row.id}",
        aggregate_id=reset_row.id,
        expires_at=reset_row.expires_at,
    )
    audit_service.record(db, "PASSWORD_RESET_REQUESTED", tenant_id=user.tenant_id, user_id=user.id)
    db.commit()
    return token if settings.DEBUG else None


def reset_password(db: Session, *, token: str, new_password: str) -> None:
    token_hash = hash_token(token)
    set_db_context(db, password_reset_hash=token_hash)
    lookup = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    if lookup is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token inválido ou já utilizado")
    set_db_context(db, tenant_id=lookup.tenant_id)
    user = db.scalar(select(User).where(User.id == lookup.user_id).with_for_update())
    reset_row = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.id == lookup.id, PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    if reset_row is None or reset_row.used_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token inválido ou já utilizado")
    if reset_row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token expirado")

    if user is None or user.id != reset_row.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conta não encontrada")

    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    reset_row.used_at = datetime.now(timezone.utc)
    set_db_context(db, password_reset_token_id=reset_row.id)
    db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.event_type == "password_reset",
            EmailOutbox.aggregate_id == reset_row.id,
            EmailOutbox.status.in_(("pending", "processing")),
        )
        .values(
            status="cancelled", processed_at=reset_row.used_at, payload_encrypted=None,
            claimed_by=None, lease_until=None, last_error="reset_token_used",
        )
    )
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    audit_service.record(db, "PASSWORD_RESET_COMPLETED", tenant_id=user.tenant_id, user_id=user.id)
    db.commit()


def change_password(
    db: Session,
    *,
    user: User,
    current_session_id: uuid.UUID,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta")
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    set_db_context(db, tenant_id=user.tenant_id)
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.id != current_session_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    audit_service.record(db, "PASSWORD_CHANGED", tenant_id=user.tenant_id, user_id=user.id)
    db.commit()


def list_sessions(db: Session, user: User, current_session_id: uuid.UUID) -> list[dict]:
    set_db_context(db, tenant_id=user.tenant_id)
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "last_seen_at": row.last_seen_at,
            "expires_at": row.expires_at,
            "current": row.id == current_session_id,
        }
        for row in rows
    ]


def revoke_session(db: Session, user: User, session_id: uuid.UUID) -> None:
    set_db_context(db, tenant_id=user.tenant_id)
    row = db.get(UserSession, session_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessão não encontrada")
    row.revoked_at = datetime.now(timezone.utc)
    audit_service.record(db, "SESSION_REVOKED", tenant_id=user.tenant_id, user_id=user.id)
    db.commit()
