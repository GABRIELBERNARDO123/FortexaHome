from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

_CONTEXT_KEYS = {
    "tenant_id": "app.tenant_id",
    "login_email_hash": "app.login_email_hash",
    "session_token_hash": "app.session_token_hash",
    "password_reset_hash": "app.password_reset_hash",
    "license_code_hash": "app.license_code_hash",
    "payment_provider": "app.payment_provider",
    "payment_order_id": "app.payment_order_id",
    "catalog_write": "app.catalog_write",
    "pending_activation_id": "app.pending_activation_id",
    "password_reset_token_id": "app.password_reset_token_id",
    "outbox_license_id": "app.outbox_license_id",
    "support_login_email_hash": "app.support_login_email_hash",
    "support_session_token_hash": "app.support_session_token_hash",
    "support_operator_id": "app.support_operator_id",
    "support_provisioning": "app.support_provisioning",
    "pending_recovery_email_hash": "app.pending_recovery_email_hash",
    "license_recovery_email_hash": "app.license_recovery_email_hash",
    "privacy_erasure": "app.privacy_erasure",
}


class Base(DeclarativeBase):
    pass


@event.listens_for(SessionLocal, "after_begin")
def _apply_context_after_begin(session: Session, transaction, connection) -> None:
    context = session.info.get("rls_context")
    if not context:
        return
    for key, value in context.items():
        guc = _CONTEXT_KEYS.get(key)
        if guc and value is not None:
            connection.execute(text("SELECT set_config(:name, :value, true)"), {"name": guc, "value": str(value)})


def set_db_context(db: Session, **kwargs: Any) -> None:
    """Aplica contexto RLS. Deve ser chamado antes das consultas protegidas."""
    context = dict(db.info.get("rls_context") or {})
    for key, value in kwargs.items():
        if key not in _CONTEXT_KEYS:
            raise ValueError(f"Contexto RLS desconhecido: {key}")
        context[key] = value
    db.info["rls_context"] = context
    for key, value in kwargs.items():
        if value is None:
            continue
        db.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": _CONTEXT_KEYS[key], "value": str(value)},
        )


def reapply_db_context(db: Session) -> None:
    """Reaplica GUCs de RLS após um commit intermediário do rate limiter."""
    context = db.info.get("rls_context") or {}
    for key, value in context.items():
        guc = _CONTEXT_KEYS.get(key)
        if guc and value is not None:
            db.execute(text("SELECT set_config(:name, :value, true)"), {"name": guc, "value": str(value)})


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if settings.is_production:
            role = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            if role.current_user != settings.APP_DB_USER:
                raise RuntimeError("A conexão operacional deve usar APP_DB_USER")
            if role.rolsuper or role.rolbypassrls:
                raise RuntimeError("O usuário operacional do banco não pode ter SUPERUSER ou BYPASSRLS")
