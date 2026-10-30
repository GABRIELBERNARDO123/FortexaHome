from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.core.deps import CurrentUser, DBSession
from app.schemas.card import CardCreate, CardPublic, CardUpdate
from app.services import card_service

router = APIRouter(prefix="/cards", tags=["cartões"])


@router.get("", response_model=list[CardPublic])
def list_cards(
    user: CurrentUser,
    db: DBSession,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> list[dict]:
    return card_service.list_cards(
        db, user.tenant_id, start=start, end=end, include_archived=include_archived
    )


@router.post("", response_model=CardPublic, status_code=status.HTTP_201_CREATED)
def create_card(payload: CardCreate, user: CurrentUser, db: DBSession) -> dict:
    return card_service.create_card(db, user, payload.model_dump())


@router.patch("/{card_id}", response_model=CardPublic)
def update_card(card_id: uuid.UUID, payload: CardUpdate, user: CurrentUser, db: DBSession) -> dict:
    return card_service.update_card(db, user, card_id, payload.model_dump(exclude_unset=True))


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_card(card_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    card_service.delete_card(db, user, card_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
