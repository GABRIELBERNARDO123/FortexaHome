from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DBSession
from app.models.tenant import Tenant
from app.services import dashboard_service
from app.services.periods import parse_month

router = APIRouter(prefix="/dashboard", tags=["painel"])


def _month(db: Session, user, month: str | None):
    tenant = db.get(Tenant, user.tenant_id)
    return parse_month(month, tenant.timezone if tenant else "America/Sao_Paulo")


@router.get("")
def dashboard(
    user: CurrentUser,
    db: DBSession,
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
) -> dict:
    return dashboard_service.summary(db, user.tenant_id, _month(db, user, month))
