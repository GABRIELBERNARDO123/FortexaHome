from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service
from app.services.category_service import get_category
from app.services.periods import month_bounds


def _spent_map(db: Session, tenant_id: uuid.UUID, start: date, end: date) -> dict[uuid.UUID, Decimal]:
    rows = db.execute(
        select(Transaction.category_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.kind == "expense",
            Transaction.occurred_on >= start,
            Transaction.occurred_on <= end,
            Transaction.category_id.is_not(None),
        )
        .group_by(Transaction.category_id)
    ).all()
    return {category_id: Decimal(total) for category_id, total in rows}


def list_budgets(db: Session, tenant_id: uuid.UUID, competence_month: date) -> list[dict]:
    start, end = month_bounds(competence_month.year, competence_month.month)
    spent_map = _spent_map(db, tenant_id, start, end)
    rows = db.execute(
        select(Budget, Category.name)
        .join(Category, Category.id == Budget.category_id)
        .where(Budget.tenant_id == tenant_id, Budget.competence_month == competence_month)
        .order_by(Category.name)
    ).all()
    result = []
    for budget, category_name in rows:
        spent = spent_map.get(budget.category_id, Decimal("0"))
        available = budget.limit_amount - spent
        percent = float(spent / budget.limit_amount * 100) if budget.limit_amount else 0.0
        result.append(
            {
                "id": budget.id,
                "category_id": budget.category_id,
                "category_name": category_name,
                "competence_month": budget.competence_month,
                "limit_amount": budget.limit_amount,
                "spent": f"{spent:.2f}",
                "available": f"{available:.2f}",
                "percent": round(percent, 1),
            }
        )
    return result


def create_budget(db: Session, user: User, data: dict) -> dict:
    category = get_category(db, user.tenant_id, data["category_id"])
    if category.kind != "expense":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Orçamentos usam categorias de despesa")
    if category.archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Categoria arquivada. Escolha uma categoria ativa.")
    existing = db.scalar(
        select(Budget).where(
            Budget.tenant_id == user.tenant_id,
            Budget.category_id == data["category_id"],
            Budget.competence_month == data["competence_month"],
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um orçamento para esta categoria neste mês. Edite o limite existente.",
        )
    budget = Budget(tenant_id=user.tenant_id, **data)
    try:
        with db.begin_nested():
            db.add(budget)
            db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um orçamento para esta categoria neste mês. Edite o limite existente.",
        ) from None
    audit_service.record(
        db, "BUDGET_CREATED", tenant_id=user.tenant_id, user_id=user.id, entity="budget", entity_id=budget.id
    )
    db.commit()
    return next(item for item in list_budgets(db, user.tenant_id, data["competence_month"]) if item["id"] == budget.id)


def update_budget(db: Session, user: User, budget_id: uuid.UUID, limit_amount: Decimal) -> dict:
    budget = db.scalar(select(Budget).where(Budget.id == budget_id, Budget.tenant_id == user.tenant_id))
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orçamento não encontrado")
    budget.limit_amount = limit_amount
    audit_service.record(
        db, "BUDGET_UPDATED", tenant_id=user.tenant_id, user_id=user.id, entity="budget", entity_id=budget.id
    )
    db.commit()
    return next(
        item for item in list_budgets(db, user.tenant_id, budget.competence_month) if item["id"] == budget.id
    )


def delete_budget(db: Session, user: User, budget_id: uuid.UUID) -> None:
    budget = db.scalar(select(Budget).where(Budget.id == budget_id, Budget.tenant_id == user.tenant_id))
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orçamento não encontrado")
    db.delete(budget)
    audit_service.record(
        db, "BUDGET_DELETED", tenant_id=user.tenant_id, user_id=user.id, entity="budget", entity_id=budget_id
    )
    db.commit()
