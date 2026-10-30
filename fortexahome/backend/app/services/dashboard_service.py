from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bill import Bill
from app.models.category import Category
from app.models.tenant import Tenant
from app.models.transaction import Transaction
from app.services import budget_service, card_service, goal_service, transaction_service
from app.services.periods import month_bounds, shift_month, today_in_timezone

MONTH_NAMES = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]
SHORT_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _money(value: Decimal | int | None) -> str:
    return f"{Decimal(value or 0):.2f}"


def _percent_change(current: Decimal, previous: Decimal) -> float | None:
    if previous == 0:
        return None
    return round(float((current - previous) / previous * 100), 1)


def _totals(db: Session, tenant_id: uuid.UUID, start: date, end: date) -> dict[str, Decimal]:
    rows = db.execute(
        select(Transaction.kind, func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.tenant_id == tenant_id, Transaction.occurred_on >= start, Transaction.occurred_on <= end)
        .group_by(Transaction.kind)
    ).all()
    totals = {kind: Decimal(total) for kind, total in rows}
    income = totals.get("income", Decimal("0"))
    expense = totals.get("expense", Decimal("0"))
    return {"income": income, "expense": expense, "result": income - expense}


def summary(db: Session, tenant_id: uuid.UUID, selected_month: date) -> dict:
    timezone_name = db.scalar(select(Tenant.timezone).where(Tenant.id == tenant_id))
    today = today_in_timezone(timezone_name or "America/Sao_Paulo")
    start, end = month_bounds(selected_month.year, selected_month.month)
    prev_year, prev_month = shift_month(selected_month.year, selected_month.month, -1)
    prev_start, prev_end = month_bounds(prev_year, prev_month)

    all_time = db.execute(
        select(Transaction.kind, func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.tenant_id == tenant_id)
        .group_by(Transaction.kind)
    ).all()
    all_totals = {kind: Decimal(total) for kind, total in all_time}
    total_balance = all_totals.get("income", Decimal("0")) - all_totals.get("expense", Decimal("0"))

    current = _totals(db, tenant_id, start, end)
    previous = _totals(db, tenant_id, prev_start, prev_end)

    pending = db.execute(
        select(Bill.status, func.coalesce(func.sum(Bill.amount), 0), func.count())
        .where(Bill.tenant_id == tenant_id)
        .group_by(Bill.status)
    ).all()
    pending_total = sum((Decimal(total) for status, total, _ in pending if status == "pending"), Decimal("0"))
    pending_count = sum((count for status, _, count in pending if status == "pending"), 0)
    overdue_count = db.scalar(
        select(func.count()).select_from(Bill).where(
            Bill.tenant_id == tenant_id,
            Bill.status == "pending",
            Bill.due_on < today,
        )
    )

    series = []
    for offset in range(-5, 1):
        year, month = shift_month(selected_month.year, selected_month.month, offset)
        s, e = month_bounds(year, month)
        totals = _totals(db, tenant_id, s, e)
        series.append(
            {
                "month": f"{year:04d}-{month:02d}",
                "label": SHORT_MONTHS[month - 1],
                "income": _money(totals["income"]),
                "expense": _money(totals["expense"]),
            }
        )

    category_label = func.coalesce(Category.name, "Sem categoria")
    category_color = func.coalesce(Category.color, "#8d8574")
    category_rows = db.execute(
        select(category_label, category_color, func.coalesce(func.sum(Transaction.amount), 0))
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.kind == "expense",
            Transaction.occurred_on >= start,
            Transaction.occurred_on <= end,
        )
        .group_by(category_label, category_color)
        .order_by(func.sum(Transaction.amount).desc())
    ).all()
    expense_total = current["expense"]
    categories = [
        {
            "name": name,
            "color": color,
            "amount": _money(amount),
            "percent": round(float(Decimal(amount) / expense_total * 100), 1) if expense_total else 0.0,
        }
        for name, color, amount in category_rows[:8]
    ]

    budgets = budget_service.list_budgets(db, tenant_id, selected_month)
    planned = sum((Decimal(item["limit_amount"]) for item in budgets), Decimal("0"))
    budget_spent = sum((Decimal(item["spent"]) for item in budgets), Decimal("0"))
    goals = goal_service.list_goals(db, tenant_id)
    active_goals = [goal for goal in goals if goal["status"] == "active"]
    cards = card_service.list_cards(db, tenant_id, start=start, end=end)
    card_limit = sum((Decimal(card["limit_amount"]) for card in cards), Decimal("0"))
    card_spent = sum((Decimal(card["spent"]) for card in cards), Decimal("0"))

    return {
        "period": {
            "month": f"{selected_month.year:04d}-{selected_month.month:02d}",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "label": f"{MONTH_NAMES[selected_month.month - 1]} de {selected_month.year}",
        },
        "total_balance": _money(total_balance),
        "income": _money(current["income"]),
        "expense": _money(current["expense"]),
        "result": _money(current["result"]),
        "previous_income": _money(previous["income"]),
        "previous_expense": _money(previous["expense"]),
        "income_change": _percent_change(current["income"], previous["income"]),
        "expense_change": _percent_change(current["expense"], previous["expense"]),
        "pending_bills_total": _money(pending_total),
        "pending_bills_count": int(pending_count or 0),
        "overdue_bills_count": int(overdue_count or 0),
        "series": series,
        "categories": categories,
        "recent_transactions": transaction_service.list_transactions(
            db, tenant_id, start=start, end=end, page=1, page_size=5
        ),
        "goals": {
            "count": len(active_goals),
            "saved": _money(sum((Decimal(goal["saved_amount"]) for goal in active_goals), Decimal("0"))),
            "target": _money(sum((Decimal(goal["target_amount"]) for goal in active_goals), Decimal("0"))),
        },
        "budgets": {
            "planned": _money(planned),
            "spent": _money(budget_spent),
            "available": _money(planned - budget_spent),
            "count": len(budgets),
        },
        "cards": {
            "count": len(cards),
            "limit": _money(card_limit),
            "spent": _money(card_spent),
            "available": _money(max(Decimal("0"), card_limit - card_spent)),
        },
    }
