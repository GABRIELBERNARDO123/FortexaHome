from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.bill import Bill
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service, idempotency_service
from app.services.category_service import get_category


def _money(value: Decimal | int | None) -> str:
    return f"{Decimal(value or 0):.2f}"


def _public(row: Transaction, category_name: str | None) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "amount": row.amount,
        "occurred_on": row.occurred_on,
        "description": row.description,
        "category_id": row.category_id,
        "category_name": category_name,
        "payment_method": row.payment_method,
        "notes": row.notes,
        "card_id": row.card_id,
        "bill_id": row.bill_id,
        "source": row.source,
        "created_at": row.created_at,
    }


def _validate_category(
    db: Session,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID | None,
    kind: str,
    *,
    allow_archived: bool = False,
) -> None:
    if category_id is None:
        return
    category = get_category(db, tenant_id, category_id)
    if category.kind != kind:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A categoria não corresponde ao tipo do lançamento",
        )
    if category.archived and not allow_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Categoria arquivada. Escolha uma categoria ativa.",
        )


def _validate_card(db: Session, tenant_id: uuid.UUID, card_id: uuid.UUID | None, payment_method: str) -> None:
    if card_id is None:
        return
    if payment_method != "credit":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cartão exige forma de pagamento crédito")
    card = db.scalar(select(CreditCard).where(CreditCard.id == card_id, CreditCard.tenant_id == tenant_id))
    if card is None or card.archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cartão inválido")


def list_transactions(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
    kind: str | None = None,
    category_id: uuid.UUID | None = None,
    search: str | None = None,
    card_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    query = (
        select(Transaction, Category.name)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(Transaction.tenant_id == tenant_id)
    )
    if start:
        query = query.where(Transaction.occurred_on >= start)
    if end:
        query = query.where(Transaction.occurred_on <= end)
    if kind:
        query = query.where(Transaction.kind == kind)
    if category_id:
        query = query.where(Transaction.category_id == category_id)
    if card_id:
        query = query.where(Transaction.card_id == card_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(Transaction.description.ilike(term), Transaction.notes.ilike(term))
        )
    query = query.order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
    query = query.offset(max(0, (page - 1) * page_size)).limit(min(page_size, 100))
    return [_public(row, category_name) for row, category_name in db.execute(query).all()]


def get_transaction(db: Session, tenant_id: uuid.UUID, transaction_id: uuid.UUID) -> Transaction:
    row = db.scalar(select(Transaction).where(Transaction.id == transaction_id, Transaction.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento não encontrado")
    return row


def create_transaction(
    db: Session, user: User, data: dict, *, idempotency_key: str | None = None
) -> dict:
    def effect() -> tuple[dict, str, uuid.UUID]:
        _validate_category(db, user.tenant_id, data.get("category_id"), data["kind"])
        _validate_card(db, user.tenant_id, data.get("card_id"), data["payment_method"])
        row = Transaction(
            tenant_id=user.tenant_id,
            user_id=user.id,
            kind=data["kind"],
            amount=data["amount"],
            occurred_on=data["occurred_on"],
            description=data["description"].strip(),
            category_id=data.get("category_id"),
            payment_method=data["payment_method"],
            notes=(data.get("notes") or "").strip() or None,
            card_id=data.get("card_id"),
            source="manual",
        )
        db.add(row)
        db.flush()
        audit_service.record(
            db, "TRANSACTION_CREATED", tenant_id=user.tenant_id, user_id=user.id, entity="transaction", entity_id=row.id
        )
        category_name = (
            db.scalar(select(Category.name).where(Category.id == row.category_id))
            if row.category_id
            else None
        )
        return _public(row, category_name), "transaction", row.id

    return idempotency_service.execute(
        db,
        user,
        operation="transactions.create",
        key=idempotency_key,
        payload=data,
        effect=effect,
    )


def update_transaction(db: Session, user: User, transaction_id: uuid.UUID, data: dict) -> dict:
    row = get_transaction(db, user.tenant_id, transaction_id)
    if row.source == "bill":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lançamento gerado por conta paga deve ser alterado na própria conta.",
        )
    new_kind = data.get("kind", row.kind)
    new_payment = data.get("payment_method", row.payment_method)
    category_id = data["category_id"] if "category_id" in data else row.category_id
    _validate_category(
        db,
        user.tenant_id,
        category_id,
        new_kind,
        allow_archived=category_id == row.category_id and new_kind == row.kind,
    )
    if "card_id" in data:
        _validate_card(db, user.tenant_id, data.get("card_id"), new_payment)
    else:
        _validate_card(db, user.tenant_id, row.card_id, new_payment)

    for field in (
        "kind",
        "amount",
        "occurred_on",
        "description",
        "category_id",
        "payment_method",
        "notes",
        "card_id",
    ):
        if field in data:
            value = data[field]
            if field == "description" and value is not None:
                value = value.strip()
            if field == "notes":
                value = (value or "").strip() or None
            setattr(row, field, value)

    audit_service.record(
        db, "TRANSACTION_UPDATED", tenant_id=user.tenant_id, user_id=user.id, entity="transaction", entity_id=row.id
    )
    db.commit()
    category_name = db.scalar(select(Category.name).where(Category.id == row.category_id)) if row.category_id else None
    return _public(row, category_name)


def delete_transaction(db: Session, user: User, transaction_id: uuid.UUID) -> None:
    row = get_transaction(db, user.tenant_id, transaction_id)
    if row.source == "bill":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desmarque o pagamento da conta antes de excluir este lançamento.",
        )
    db.delete(row)
    audit_service.record(
        db, "TRANSACTION_DELETED", tenant_id=user.tenant_id, user_id=user.id, entity="transaction", entity_id=transaction_id
    )
    db.commit()


def summary(db: Session, tenant_id: uuid.UUID, *, start: date, end: date) -> dict:
    rows = db.execute(
        select(Transaction.kind, func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.tenant_id == tenant_id, Transaction.occurred_on >= start, Transaction.occurred_on <= end)
        .group_by(Transaction.kind)
    ).all()
    totals = {kind: Decimal(total) for kind, total in rows}
    income = totals.get("income", Decimal("0"))
    expense = totals.get("expense", Decimal("0"))
    count = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.tenant_id == tenant_id, Transaction.occurred_on >= start, Transaction.occurred_on <= end)
    )
    return {
        "income": _money(income),
        "expense": _money(expense),
        "result": _money(income - expense),
        "count": int(count or 0),
    }
