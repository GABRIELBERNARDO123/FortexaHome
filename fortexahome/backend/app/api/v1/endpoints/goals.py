from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.core.deps import CurrentUser, DBSession
from app.schemas.goal import (
    GoalCreate,
    GoalMovementCreate,
    GoalMovementPublic,
    GoalPublic,
    GoalUpdate,
)
from app.services import goal_service

router = APIRouter(prefix="/goals", tags=["metas"])


@router.get("", response_model=list[GoalPublic])
def list_goals(user: CurrentUser, db: DBSession) -> list[dict]:
    return goal_service.list_goals(db, user.tenant_id)


@router.post("", response_model=GoalPublic, status_code=status.HTTP_201_CREATED)
def create_goal(payload: GoalCreate, user: CurrentUser, db: DBSession) -> dict:
    return goal_service.create_goal(db, user, payload.model_dump())


@router.patch("/{goal_id}", response_model=GoalPublic)
def update_goal(goal_id: uuid.UUID, payload: GoalUpdate, user: CurrentUser, db: DBSession) -> dict:
    return goal_service.update_goal(db, user, goal_id, payload.model_dump(exclude_unset=True))


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: uuid.UUID, user: CurrentUser, db: DBSession) -> Response:
    goal_service.delete_goal(db, user, goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{goal_id}/movements", response_model=list[GoalMovementPublic])
def list_movements(goal_id: uuid.UUID, user: CurrentUser, db: DBSession) -> list[dict]:
    return goal_service.list_movements(db, user.tenant_id, goal_id)


@router.post("/{goal_id}/movements", status_code=status.HTTP_201_CREATED)
def add_movement(
    goal_id: uuid.UUID, payload: GoalMovementCreate, user: CurrentUser, db: DBSession
) -> dict:
    return goal_service.add_movement(db, user, goal_id, payload.model_dump())
