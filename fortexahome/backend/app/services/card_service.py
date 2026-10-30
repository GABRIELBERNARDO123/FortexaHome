from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service


def _card_public(card: CreditCard, spent: Decimal) -> dict:
    available = max(Decimal("0"), card.limit_amount - spent)
    return {
        "id": card.id,
        "name": card.name,
        "institution": card.institution,
        "limit_amount": card.limit_amount,
        "closing_day": card.closing_day,
        "due_day": card.due_day,
        "archived": card.archived,
        "spent": f"{spent:.2f}",
        "available": f"{available:.2f}",
    }


def get_card(db: Session, tenant_id: uuid.UUID, card_id: uuid.UUID) -> CreditCard:
    card = db.scalar(select(CreditCard).where(CreditCard.id == card_id, CreditCard.tenant_id == tenant_id))
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartão não encontrado")
    return card


def list_cards(
    db: Session, tenant_id: uuid.UUID, *, start: date | None = None, end: date | None = None, include_archived: bool = False
) -> list[dict]:
    query = select(CreditCard).where(CreditCard.tenant_id == tenant_id)
    if not include_archived:
        query = query.where(CreditCard.archived.is_(False))
    cards = db.scalars(query.order_by(CreditCard.name)).all()

    spend_query = (
        select(Transaction.card_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.kind == "expense",
            Transaction.card_id.is_not(None),
        )
        .group_by(Transaction.card_id)
    )
    if start:
        spend_query = spend_query.where(Transaction.occurred_on >= start)
    if end:
        spend_query = spend_query.where(Transaction.occurred_on <= end)
    spent_by_card = {card_id: Decimal(total) for card_id, total in db.execute(spend_query).all()}
    return [_card_public(card, spent_by_card.get(card.id, Decimal("0"))) for card in cards]


def create_card(db: Session, user: User, data: dict) -> dict:
    card = CreditCard(tenant_id=user.tenant_id, **data)
    db.add(card)
    db.flush()
    audit_service.record(
        db, "CARD_CREATED", tenant_id=user.tenant_id, user_id=user.id, entity="credit_card", entity_id=card.id
    )
    db.commit()
    return _card_public(card, Decimal("0"))


def update_card(db: Session, user: User, card_id: uuid.UUID, data: dict) -> dict:
    card = get_card(db, user.tenant_id, card_id)
    for field, value in data.items():
        setattr(card, field, value)
    audit_service.record(
        db, "CARD_UPDATED", tenant_id=user.tenant_id, user_id=user.id, entity="credit_card", entity_id=card.id
    )
    db.commit()
    result = list_cards(db, user.tenant_id, include_archived=True)
    return next(item for item in result if item["id"] == card.id)


def delete_card(db: Session, user: User, card_id: uuid.UUID) -> None:
    card = get_card(db, user.tenant_id, card_id)
    card.archived = True
    audit_service.record(
        db, "CARD_ARCHIVED", tenant_id=user.tenant_id, user_id=user.id, entity="credit_card", entity_id=card.id
    )
    db.commit()
