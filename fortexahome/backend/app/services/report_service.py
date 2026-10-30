from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.transaction import Transaction
from app.services.periods import month_bounds, shift_month


def _money(value: Decimal | int | None) -> str:
    return f"{Decimal(value or 0):.2f}"


def period_report(db: Session, tenant_id: uuid.UUID, start: date, end: date) -> dict:
    totals_rows = db.execute(
        select(Transaction.kind, func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.tenant_id == tenant_id, Transaction.occurred_on >= start, Transaction.occurred_on <= end)
        .group_by(Transaction.kind)
    ).all()
    totals = {kind: Decimal(total) for kind, total in totals_rows}
    income = totals.get("income", Decimal("0"))
    expense = totals.get("expense", Decimal("0"))

    category_label = func.coalesce(Category.name, "Sem categoria")
    category_color = func.coalesce(Category.color, "#8d8574")
    category_rows = db.execute(
        select(category_label, category_color, func.coalesce(func.sum(Transaction.amount), 0), func.count())
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

    month_rows = db.execute(
        select(
            func.date_trunc("month", Transaction.occurred_on).label("month"),
            Transaction.kind,
            func.coalesce(func.sum(Transaction.amount), 0),
        )
        .where(Transaction.tenant_id == tenant_id, Transaction.occurred_on >= start, Transaction.occurred_on <= end)
        .group_by("month", Transaction.kind)
        .order_by("month")
    ).all()
    by_month: dict[str, dict[str, str]] = {}
    for month_value, kind, amount in month_rows:
        key = month_value.strftime("%Y-%m") if hasattr(month_value, "strftime") else str(month_value)[:7]
        by_month.setdefault(key, {"income": "0.00", "expense": "0.00"})[kind] = _money(amount)

    count = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.tenant_id == tenant_id, Transaction.occurred_on >= start, Transaction.occurred_on <= end)
    )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "income": _money(income),
        "expense": _money(expense),
        "result": _money(income - expense),
        "count": int(count or 0),
        "by_category": [
            {
                "name": name,
                "color": color,
                "amount": _money(amount),
                "count": int(item_count),
                "percent": round(float(Decimal(amount) / expense * 100), 1) if expense else 0.0,
            }
            for name, color, amount, item_count in category_rows
        ],
        "by_month": [{"month": month, **values} for month, values in sorted(by_month.items())],
    }


def transactions_csv(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
) -> str:
    query = (
        select(Transaction, Category.name)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(Transaction.tenant_id == tenant_id)
    )
    if start:
        query = query.where(Transaction.occurred_on >= start)
    if end:
        query = query.where(Transaction.occurred_on <= end)
    rows = db.execute(query.order_by(Transaction.occurred_on, Transaction.created_at)).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["Data", "Tipo", "Descrição", "Categoria", "Forma de pagamento", "Valor", "Observações"])
    for transaction, category_name in rows:
        writer.writerow(
            [
                transaction.occurred_on.isoformat(),
                "Receita" if transaction.kind == "income" else "Despesa",
                transaction.description,
                category_name or "",
                transaction.payment_method,
                f"{transaction.amount:.2f}",
                transaction.notes or "",
            ]
        )
    return "\ufeff" + buffer.getvalue()


def monthly_report(db: Session, tenant_id: uuid.UUID, selected_month: date) -> dict:
    start, end = month_bounds(selected_month.year, selected_month.month)
    return period_report(db, tenant_id, start, end)
