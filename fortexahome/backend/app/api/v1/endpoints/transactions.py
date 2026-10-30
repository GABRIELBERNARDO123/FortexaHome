from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Response, status

from app.core.deps import CurrentUser, DBSession
from app.schemas.transaction import (
    TransactionCreate,
    TransactionPublic,
    TransactionSummary,
    TransactionUpdate,
)
from app.services import transaction_service

router = APIRouter(prefix="/transactions", tags=["lançamentos"])


@router.get("/summary", response_model=TransactionSummary)
def summary(
    user: CurrentUser,
    db: DBSession,
    start: date = Query(...),
    end: date = Query(...),
) -> dict:
    return transaction_service.summary(db, user.tenant_id, start=start, end=end)


@router.get("", response_model=list[TransactionPublic])
def list_transactions(
    user: CurrentUser,
    db: DBSession,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    kind: Literal["income", "expense"] | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    card_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    return transaction_service.list_transactions(
        db,
        user.tenant_id,
        start=start,
        end=end,
        kind=kind,
        category_id=category_id,
        card_id=card_id,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TransactionPublic, status_code=status.HTTP_201_CREATED)
def create_transaction(payload: TransactionCreate, user: CurrentUser, db: DBSession) -> dict:
    return transaction_service.create_transaction(db, user, payload.model_dump())


@router.patch("/{transaction_id}", response_model=TransactionPublic)
def update_transaction(
    transaction_id: uuid.UUID, payload: TransactionUpdate, user: CurrentUser, db: DBSession
) -> dict:
    return transaction_service.update_transaction(
        db, user, transaction_id, payload.model_dump(exclude_unset=True)
    )


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(transaction_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    transaction_service.delete_transaction(db, user, transaction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
