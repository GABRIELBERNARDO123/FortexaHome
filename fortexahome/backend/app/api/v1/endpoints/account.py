from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentAuth, CurrentUser, DBSession
from app.models.bill import Bill
from app.models.budget import Budget
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.goal import Goal
from app.models.goal_movement import GoalMovement
from app.models.transaction import Transaction
from app.schemas.account import AccountPublic, AccountUpdate
from app.services import account_service

router = APIRouter(prefix="/account", tags=["conta"])


def _value(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _dump(row, fields: list[str]) -> dict:
    return {field: _value(getattr(row, field)) for field in fields}


@router.get("", response_model=AccountPublic)
def get_account(user: CurrentUser, db: DBSession) -> dict:
    return account_service.account_payload(db, user)


@router.patch("", response_model=AccountPublic)
def update_account(payload: AccountUpdate, ctx: CurrentAuth, db: DBSession) -> dict:
    return account_service.update_account(db, ctx.user, payload.model_dump(exclude_unset=True))


@router.get("/export")
def export_account(user: CurrentUser, db: DBSession) -> dict:
    tenant_id = user.tenant_id
    transactions = db.scalars(
        select(Transaction).where(Transaction.tenant_id == tenant_id).order_by(Transaction.occurred_on)
    ).all()
    bills = db.scalars(select(Bill).where(Bill.tenant_id == tenant_id).order_by(Bill.due_on)).all()
    categories = db.scalars(select(Category).where(Category.tenant_id == tenant_id).order_by(Category.name)).all()
    cards = db.scalars(select(CreditCard).where(CreditCard.tenant_id == tenant_id).order_by(CreditCard.name)).all()
    budgets = db.scalars(
        select(Budget).where(Budget.tenant_id == tenant_id).order_by(Budget.competence_month)
    ).all()
    goals = db.scalars(select(Goal).where(Goal.tenant_id == tenant_id).order_by(Goal.created_at)).all()
    movements = db.scalars(
        select(GoalMovement).where(GoalMovement.tenant_id == tenant_id).order_by(GoalMovement.occurred_on)
    ).all()

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": account_service.account_payload(db, user),
        "categories": [
            _dump(row, ["name", "kind", "color", "icon", "is_system", "created_at"]) for row in categories
        ],
        "transactions": [
            _dump(
                row,
                [
                    "kind",
                    "amount",
                    "occurred_on",
                    "description",
                    "category_id",
                    "payment_method",
                    "notes",
                    "card_id",
                    "bill_id",
                    "source",
                    "created_at",
                ],
            )
            for row in transactions
        ],
        "bills": [
            _dump(
                row,
                [
                    "name",
                    "category_id",
                    "amount",
                    "due_on",
                    "status",
                    "paid_at",
                    "recurrence",
                    "notes",
                    "created_at",
                ],
            )
            for row in bills
        ],
        "cards": [
            _dump(
                row,
                ["name", "institution", "limit_amount", "closing_day", "due_day", "archived", "created_at"],
            )
            for row in cards
        ],
        "budgets": [
            _dump(row, ["category_id", "competence_month", "limit_amount", "created_at"]) for row in budgets
        ],
        "goals": [
            _dump(
                row,
                [
                    "name",
                    "description",
                    "target_amount",
                    "target_date",
                    "icon",
                    "status",
                    "completed_at",
                    "created_at",
                ],
            )
            for row in goals
        ],
        "goal_movements": [
            _dump(row, ["goal_id", "kind", "amount", "occurred_on", "note", "created_at"]) for row in movements
        ],
    }
