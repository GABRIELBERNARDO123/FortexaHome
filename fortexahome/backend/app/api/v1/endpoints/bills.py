from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Response, status

from app.core.deps import CurrentUser, DBSession
from app.schemas.bill import BillCreate, BillPublic, BillUpdate
from app.services import bill_service, idempotency_service

router = APIRouter(prefix="/bills", tags=["contas a pagar"])


@router.get("", response_model=list[BillPublic])
def list_bills(
    user: CurrentUser,
    db: DBSession,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    status_filter: Literal["pending", "paid"] | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=120),
) -> list[dict]:
    return bill_service.list_bills(
        db, user.tenant_id, start=start, end=end, status_filter=status_filter, search=search
    )


@router.post("", response_model=BillPublic, status_code=status.HTTP_201_CREATED)
def create_bill(
    payload: BillCreate,
    user: CurrentUser,
    db: DBSession,
    idempotency_key: idempotency_service.IdempotencyKeyHeader = None,
) -> dict:
    return bill_service.create_bill(db, user, payload.model_dump(), idempotency_key=idempotency_key)


@router.patch("/{bill_id}", response_model=BillPublic)
def update_bill(bill_id: uuid.UUID, payload: BillUpdate, user: CurrentUser, db: DBSession) -> dict:
    return bill_service.update_bill(db, user, bill_id, payload.model_dump(exclude_unset=True))


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(bill_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    bill_service.delete_bill(db, user, bill_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{bill_id}/pay", response_model=BillPublic)
def pay_bill(
    bill_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    idempotency_key: idempotency_service.IdempotencyKeyHeader = None,
) -> dict:
    return bill_service.pay_bill(db, user, bill_id, idempotency_key=idempotency_key)


@router.post("/{bill_id}/unpay", response_model=BillPublic)
def unpay_bill(
    bill_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    idempotency_key: idempotency_service.IdempotencyKeyHeader = None,
) -> dict:
    return bill_service.unpay_bill(db, user, bill_id, idempotency_key=idempotency_key)


@router.post("/{bill_id}/recurrence", response_model=BillPublic, status_code=status.HTTP_201_CREATED)
def generate_recurrence(bill_id: uuid.UUID, user: CurrentUser, db: DBSession) -> dict:
    return bill_service.generate_next_recurrence(db, user, bill_id)
