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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
