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
from app.models.license import License
from app.models.session import UserSession
from app.models.tenant import Tenant
from app.models.user import User

DBSession = Annotated[Session, Depends(get_db)]
settings = get_settings()


@dataclass
class AuthContext:
    user: User
    session: UserSession
    license: License | None


def _unauthorized(detail: str = "Sessão inválida ou expirada") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Cookie"},
    )


def _resolve_auth(
    request: Request,
    db: Session,
    session_cookie: str | None,
    *,
    require_active_license: bool,
) -> AuthContext:
    token = session_cookie or request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise _unauthorized("Autenticação necessária")

    token_hash = hash_token(token)
    set_db_context(db, session_token_hash=token_hash)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if session is None:
        raise _unauthorized()
    now = datetime.now(timezone.utc)
    if session.revoked_at is not None or session.expires_at <= now:
        raise _unauthorized()

    set_db_context(db, tenant_id=session.tenant_id)
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta indisponível")

    license_row = db.scalar(select(License).where(License.tenant_id == session.tenant_id))
    if license_row is None:
        if require_active_license:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Licença não encontrada para esta conta"
            )
        return AuthContext(user=user, session=session, license=None)

    if require_active_license:
        expired = license_row.expires_at is not None and license_row.expires_at <= now
        if license_row.status != "active" or expired:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Licença inativa. Regularize o acesso para continuar",
            )

    return AuthContext(user=user, session=session, license=license_row)


def get_auth_context(
    request: Request,
    db: DBSession,
    session_cookie: Annotated[str | None, Cookie(alias=settings.SESSION_COOKIE_NAME)] = None,
) -> AuthContext:
    return _resolve_auth(request, db, session_cookie, require_active_license=True)


def get_auth_context_soft(
    request: Request,
    db: DBSession,
    session_cookie: Annotated[str | None, Cookie(alias=settings.SESSION_COOKIE_NAME)] = None,
) -> AuthContext:
    return _resolve_auth(request, db, session_cookie, require_active_license=False)


def get_current_user(ctx: Annotated[AuthContext, Depends(get_auth_context)]) -> User:
    return ctx.user


def get_current_tenant(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: DBSession,
) -> Tenant:
    tenant = db.get(Tenant, ctx.user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada")
    return tenant


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]
CurrentSoftAuth = Annotated[AuthContext, Depends(get_auth_context_soft)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
DBSessionDep = DBSession
