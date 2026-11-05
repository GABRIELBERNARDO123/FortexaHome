from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.bill import Bill
from app.models.category import Category
from app.models.tenant import Tenant
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service, idempotency_service, transaction_service
from app.services.category_service import get_category
from app.services.periods import today_in_timezone


def _today(db: Session, tenant_id: uuid.UUID) -> date:
    timezone_name = db.scalar(select(Tenant.timezone).where(Tenant.id == tenant_id))
    return today_in_timezone(timezone_name or "America/Sao_Paulo")


def _public(
    bill: Bill,
    category_name: str | None,
    transaction_id: uuid.UUID | None,
    today: date | None = None,
) -> dict:
    return {
        "id": bill.id,
        "name": bill.name,
        "category_id": bill.category_id,
        "category_name": category_name,
        "amount": bill.amount,
        "due_on": bill.due_on,
        "status": bill.status,
        "paid_at": bill.paid_at,
        "recurrence": bill.recurrence,
        "parent_bill_id": bill.parent_bill_id,
        "notes": bill.notes,
        "transaction_id": transaction_id,
        "is_overdue": bill.status == "pending" and bill.due_on < (today or date.today()),
    }


def _validate_expense_category(
    db: Session,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID | None,
    *,
    allow_archived: bool = False,
) -> None:
    if category_id is None:
        return
    category = get_category(db, tenant_id, category_id)
    if category.kind != "expense":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contas a pagar exigem categoria de despesa")
    if category.archived and not allow_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Categoria arquivada. Escolha uma categoria ativa.",
        )


def get_bill(db: Session, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill:
    row = db.scalar(
        select(Bill)
        .where(Bill.id == bill_id, Bill.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada")
    return row


def list_bills(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
    status_filter: str | None = None,
    search: str | None = None,
) -> list[dict]:
    query = (
        select(Bill, Category.name, Transaction.id)
        .outerjoin(Category, Category.id == Bill.category_id)
        .outerjoin(Transaction, Transaction.bill_id == Bill.id)
        .where(Bill.tenant_id == tenant_id)
    )
    if start:
        query = query.where(Bill.due_on >= start)
    if end:
        query = query.where(Bill.due_on <= end)
    if status_filter:
        query = query.where(Bill.status == status_filter)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Bill.name.ilike(term), Bill.notes.ilike(term)))
    rows = db.execute(query.order_by(Bill.due_on, Bill.created_at)).all()
    today = _today(db, tenant_id)
    return [
        _public(bill, category_name, transaction_id, today=today)
        for bill, category_name, transaction_id in rows
    ]


def create_bill(
    db: Session, user: User, data: dict, *, idempotency_key: str | None = None
) -> dict:
    def effect() -> tuple[dict, str, uuid.UUID]:
        _validate_expense_category(db, user.tenant_id, data.get("category_id"))
        row = Bill(
            tenant_id=user.tenant_id,
            name=data["name"].strip(),
            category_id=data.get("category_id"),
            amount=data["amount"],
            due_on=data["due_on"],
            recurrence=data["recurrence"],
            notes=(data.get("notes") or "").strip() or None,
            status="pending",
        )
        db.add(row)
        db.flush()
        audit_service.record(
            db, "BILL_CREATED", tenant_id=user.tenant_id, user_id=user.id, entity="bill", entity_id=row.id
        )
        category_name = (
            db.scalar(select(Category.name).where(Category.id == row.category_id))
            if row.category_id
            else None
        )
        return _public(row, category_name, None, today=_today(db, user.tenant_id)), "bill", row.id

    return idempotency_service.execute(
        db,
        user,
        operation="bills.create",
        key=idempotency_key,
        payload=data,
        effect=effect,
    )


def update_bill(db: Session, user: User, bill_id: uuid.UUID, data: dict) -> dict:
    row = get_bill(db, user.tenant_id, bill_id)
    if row.status == "paid" and ({"amount", "due_on"} & set(data)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desmarque o pagamento antes de alterar valor ou vencimento.",
        )
    if "category_id" in data:
        _validate_expense_category(
            db,
            user.tenant_id,
            data.get("category_id"),
            allow_archived=data.get("category_id") == row.category_id,
        )
    for field in ("name", "category_id", "amount", "due_on", "recurrence", "notes"):
        if field in data:
            value = data[field]
            if field == "name" and value is not None:
                value = value.strip()
            if field == "notes":
                value = (value or "").strip() or None
            setattr(row, field, value)
    audit_service.record(
        db, "BILL_UPDATED", tenant_id=user.tenant_id, user_id=user.id, entity="bill", entity_id=row.id
    )
    db.commit()
    category_name = db.scalar(select(Category.name).where(Category.id == row.category_id)) if row.category_id else None
    transaction_id = db.scalar(select(Transaction.id).where(Transaction.bill_id == row.id))
    return _public(row, category_name, transaction_id, today=_today(db, user.tenant_id))


def delete_bill(db: Session, user: User, bill_id: uuid.UUID) -> None:
    row = get_bill(db, user.tenant_id, bill_id)
    if row.status == "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desmarque o pagamento antes de excluir esta conta.",
        )
    db.delete(row)
    audit_service.record(
        db, "BILL_DELETED", tenant_id=user.tenant_id, user_id=user.id, entity="bill", entity_id=bill_id
    )
    db.commit()


def pay_bill(
    db: Session, user: User, bill_id: uuid.UUID, *, idempotency_key: str | None = None
) -> dict:
    def effect() -> tuple[dict, str, uuid.UUID]:
        row = get_bill(db, user.tenant_id, bill_id)
        if row.status == "paid":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta conta já está paga")
        _validate_expense_category(db, user.tenant_id, row.category_id, allow_archived=True)

        transaction = Transaction(
            tenant_id=user.tenant_id,
            user_id=user.id,
            kind="expense",
            amount=row.amount,
            occurred_on=_today(db, user.tenant_id),
            description=row.name,
            category_id=row.category_id,
            payment_method="boleto",
            notes="Despesa gerada automaticamente pelo pagamento da conta.",
            bill_id=row.id,
            source="bill",
        )
        db.add(transaction)
        db.flush()
        row.status = "paid"
        row.paid_at = datetime.now(timezone.utc)
        audit_service.record(
            db, "BILL_PAID", tenant_id=user.tenant_id, user_id=user.id, entity="bill", entity_id=row.id
        )
        category_name = (
            db.scalar(select(Category.name).where(Category.id == row.category_id))
            if row.category_id
            else None
        )
        return _public(row, category_name, transaction.id, today=_today(db, user.tenant_id)), "bill", row.id

    return idempotency_service.execute(
        db,
        user,
        operation="bills.pay",
        key=idempotency_key,
        payload={"bill_id": bill_id},
        effect=effect,
    )


def unpay_bill(
    db: Session, user: User, bill_id: uuid.UUID, *, idempotency_key: str | None = None
) -> dict:
    def effect() -> tuple[dict, str, uuid.UUID]:
        row = get_bill(db, user.tenant_id, bill_id)
        if row.status != "paid":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta conta não está paga")
        transaction = db.scalar(select(Transaction).where(Transaction.bill_id == row.id))
        if transaction is not None:
            db.delete(transaction)
        row.status = "pending"
        row.paid_at = None
        audit_service.record(
            db, "BILL_REOPENED", tenant_id=user.tenant_id, user_id=user.id, entity="bill", entity_id=row.id
        )
        category_name = (
            db.scalar(select(Category.name).where(Category.id == row.category_id))
            if row.category_id
            else None
        )
        return _public(row, category_name, None, today=_today(db, user.tenant_id)), "bill", row.id

    return idempotency_service.execute(
        db,
        user,
        operation="bills.unpay",
        key=idempotency_key,
        payload={"bill_id": bill_id},
        effect=effect,
    )


def generate_next_recurrence(db: Session, user: User, bill_id: uuid.UUID) -> dict:
    row = get_bill(db, user.tenant_id, bill_id)
    if row.recurrence != "monthly":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta conta não é recorrente")
    year = row.due_on.year + (1 if row.due_on.month == 12 else 0)
    month = 1 if row.due_on.month == 12 else row.due_on.month + 1
    day = min(row.due_on.day, calendar.monthrange(year, month)[1])
    next_due = date(year, month, day)
    parent_id = row.parent_bill_id or row.id

    existing = db.scalar(
        select(Bill).where(Bill.parent_bill_id == parent_id, Bill.due_on == next_due)
    )
    if existing is not None:
        category_name = (
            db.scalar(select(Category.name).where(Category.id == existing.category_id))
            if existing.category_id
            else None
        )
        transaction_id = db.scalar(select(Transaction.id).where(Transaction.bill_id == existing.id))
        return _public(existing, category_name, transaction_id, today=_today(db, user.tenant_id))

    next_bill = Bill(
        tenant_id=user.tenant_id,
        name=row.name,
        category_id=row.category_id,
        amount=row.amount,
        due_on=next_due,
        recurrence="monthly",
        parent_bill_id=parent_id,
        notes=row.notes,
        status="pending",
    )
    try:
        with db.begin_nested():
            db.add(next_bill)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Bill).where(Bill.parent_bill_id == parent_id, Bill.due_on == next_due)
        )
        if existing is None:
            raise
        category_name = (
            db.scalar(select(Category.name).where(Category.id == existing.category_id))
            if existing.category_id
            else None
        )
        transaction_id = db.scalar(select(Transaction.id).where(Transaction.bill_id == existing.id))
        return _public(existing, category_name, transaction_id, today=_today(db, user.tenant_id))
    audit_service.record(
        db,
        "BILL_RECURRENCE_CREATED",
        tenant_id=user.tenant_id,
        user_id=user.id,
        entity="bill",
        entity_id=next_bill.id,
    )
    db.commit()
    category_name = (
        db.scalar(select(Category.name).where(Category.id == next_bill.category_id))
        if next_bill.category_id
        else None
    )
    return _public(next_bill, category_name, None, today=_today(db, user.tenant_id))
