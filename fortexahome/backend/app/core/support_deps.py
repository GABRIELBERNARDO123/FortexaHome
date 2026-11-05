from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db, set_db_context
from app.core.security import hash_token
from app.models.support import SupportOperator, SupportSession

settings = get_settings()
DBSession = Annotated[Session, Depends(get_db)]


@dataclass
class SupportContext:
    operator: SupportOperator
    session: SupportSession


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessão de suporte inválida ou expirada",
        headers={"WWW-Authenticate": "Cookie"},
    )


def get_support_context(
    request: Request,
    db: DBSession,
    support_cookie: Annotated[str | None, Cookie(alias=settings.SUPPORT_SESSION_COOKIE_NAME)] = None,
) -> SupportContext:
    token = support_cookie or request.cookies.get(settings.SUPPORT_SESSION_COOKIE_NAME)
    if not token:
        raise _unauthorized()
    token_hash = hash_token(token)
    set_db_context(db, support_session_token_hash=token_hash)
    session = db.scalar(select(SupportSession).where(SupportSession.token_hash == token_hash))
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise _unauthorized()
    set_db_context(db, support_operator_id=session.operator_id)
    operator = db.get(SupportOperator, session.operator_id)
    if operator is None or operator.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador de suporte indisponível")
    return SupportContext(operator=operator, session=session)


CurrentSupport = Annotated[SupportContext, Depends(get_support_context)]
SupportDBSession = DBSession
