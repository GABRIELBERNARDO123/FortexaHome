from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response, status

from app.core.deps import CurrentUser, DBSession
from app.core.permissions import require_owner
from app.schemas.category import CategoryCreate, CategoryPublic, CategoryUpdate
from app.services import category_service

router = APIRouter(prefix="/categories", tags=["categorias"])


@router.get("", response_model=list[CategoryPublic])
def list_categories(
    user: CurrentUser,
    db: DBSession,
    kind: Literal["income", "expense"] | None = Query(default=None),
) -> list[dict]:
    return category_service.list_categories(db, user.tenant_id, kind)


@router.post("", response_model=CategoryPublic, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, user: CurrentUser, db: DBSession) -> dict:
    require_owner(user)
    return category_service.create_category(
        db,
        user,
        name=payload.name,
        kind=payload.kind,
        color=payload.color,
        icon=payload.icon,
    )


@router.patch("/{category_id}", response_model=CategoryPublic)
def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, user: CurrentUser, db: DBSession
) -> dict:
    require_owner(user)
    return category_service.update_category(db, user, category_id, payload.model_dump(exclude_unset=True))


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    require_owner(user)
    category_service.delete_category(db, user, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
