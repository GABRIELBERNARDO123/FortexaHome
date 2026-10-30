from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DBSession
from app.models.tenant import Tenant
from app.schemas.budget import BudgetCreate, BudgetPublic, BudgetUpdate
from app.services import budget_service
from app.services.periods import month_bounds, parse_month

router = APIRouter(prefix="/budgets", tags=["orçamentos"])


def _month(db: Session, user, month: str | None):
    tenant = db.get(Tenant, user.tenant_id)
    timezone_name = tenant.timezone if tenant else "America/Sao_Paulo"
    return parse_month(month, timezone_name)


@router.get("", response_model=list[BudgetPublic])
def list_budgets(
    user: CurrentUser,
    db: DBSession,
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
) -> list[dict]:
    return budget_service.list_budgets(db, user.tenant_id, _month(db, user, month))


@router.post("", response_model=BudgetPublic, status_code=status.HTTP_201_CREATED)
def create_budget(payload: BudgetCreate, user: CurrentUser, db: DBSession) -> dict:
    return budget_service.create_budget(db, user, payload.model_dump())


@router.patch("/{budget_id}", response_model=BudgetPublic)
def update_budget(budget_id: uuid.UUID, payload: BudgetUpdate, user: CurrentUser, db: DBSession) -> dict:
    return budget_service.update_budget(db, user, budget_id, payload.limit_amount)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    budget_service.delete_budget(db, user, budget_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
