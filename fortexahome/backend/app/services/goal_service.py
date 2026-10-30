from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.goal import Goal
from app.models.goal_movement import GoalMovement
from app.models.tenant import Tenant
from app.models.user import User
from app.services import audit_service
from app.services.periods import today_in_timezone


def _saved_amounts(db: Session, tenant_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    rows = db.execute(
        select(
            GoalMovement.goal_id,
            func.coalesce(
                func.sum(
                    case(
                        (GoalMovement.kind == "deposit", GoalMovement.amount),
                        else_=-GoalMovement.amount,
                    )
                ),
                0,
            ),
        )
        .where(GoalMovement.tenant_id == tenant_id)
        .group_by(GoalMovement.goal_id)
    ).all()
    return {goal_id: Decimal(total) for goal_id, total in rows}


def _today(db: Session, tenant_id: uuid.UUID) -> date:
    timezone_name = db.scalar(select(Tenant.timezone).where(Tenant.id == tenant_id))
    return today_in_timezone(timezone_name or "America/Sao_Paulo")


def _projection(goal: Goal, saved: Decimal, today: date | None = None) -> str | None:
    if goal.target_date is None:
        return None
    today = today or date.today()
    remaining = max(Decimal("0"), goal.target_amount - saved)
    months = (goal.target_date.year - today.year) * 12 + (goal.target_date.month - today.month)
    months = max(1, months)
    return f"{remaining / Decimal(months):.2f}"


def _public(goal: Goal, saved: Decimal, today: date | None = None) -> dict:
    target = Decimal(goal.target_amount)
    remaining = max(Decimal("0"), target - saved)
    percent = float(min(Decimal("100"), (saved / target * 100) if target > 0 else Decimal("0")))
    return {
        "id": goal.id,
        "name": goal.name,
        "description": goal.description,
        "target_amount": goal.target_amount,
        "target_date": goal.target_date,
        "icon": goal.icon,
        "status": goal.status,
        "saved_amount": f"{saved:.2f}",
        "remaining_amount": f"{remaining:.2f}",
        "progress_percent": round(percent, 1),
        "projected_monthly": _projection(goal, saved, today),
        "created_at": goal.created_at,
    }


def list_goals(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    saved_map = _saved_amounts(db, tenant_id)
    goals = db.scalars(select(Goal).where(Goal.tenant_id == tenant_id).order_by(Goal.created_at.desc())).all()
    today = _today(db, tenant_id)
    return [_public(goal, saved_map.get(goal.id, Decimal("0")), today) for goal in goals]


def get_goal(db: Session, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> Goal:
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.tenant_id == tenant_id))
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meta não encontrada")
    return goal


def create_goal(db: Session, user: User, data: dict) -> dict:
    goal = Goal(tenant_id=user.tenant_id, **data)
    db.add(goal)
    db.flush()
    audit_service.record(
        db, "GOAL_CREATED", tenant_id=user.tenant_id, user_id=user.id, entity="goal", entity_id=goal.id
    )
    db.commit()
    return _public(goal, Decimal("0"), _today(db, user.tenant_id))


def update_goal(db: Session, user: User, goal_id: uuid.UUID, data: dict) -> dict:
    goal = get_goal(db, user.tenant_id, goal_id)
    for field, value in data.items():
        setattr(goal, field, value)
    audit_service.record(
        db, "GOAL_UPDATED", tenant_id=user.tenant_id, user_id=user.id, entity="goal", entity_id=goal.id
    )
    db.commit()
    saved = _saved_amounts(db, user.tenant_id).get(goal.id, Decimal("0"))
    return _public(goal, saved, _today(db, user.tenant_id))


def delete_goal(db: Session, user: User, goal_id: uuid.UUID) -> None:
    goal = get_goal(db, user.tenant_id, goal_id)
    db.delete(goal)
    audit_service.record(
        db, "GOAL_DELETED", tenant_id=user.tenant_id, user_id=user.id, entity="goal", entity_id=goal_id
    )
    db.commit()


def add_movement(db: Session, user: User, goal_id: uuid.UUID, data: dict) -> dict:
    goal = get_goal(db, user.tenant_id, goal_id)
    saved = _saved_amounts(db, user.tenant_id).get(goal.id, Decimal("0"))
    amount = Decimal(data["amount"])
    if data["kind"] == "withdrawal" and amount > saved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A retirada não pode ser maior que o valor guardado na meta",
        )
    movement = GoalMovement(
        tenant_id=user.tenant_id,
        goal_id=goal.id,
        created_by=user.id,
        kind=data["kind"],
        amount=amount,
        occurred_on=data.get("occurred_on") or _today(db, user.tenant_id),
        note=(data.get("note") or "").strip() or None,
    )
    db.add(movement)
    db.flush()

    new_saved = saved + amount if data["kind"] == "deposit" else saved - amount
    if new_saved >= Decimal(goal.target_amount) and goal.status == "active":
        goal.status = "completed"
        goal.completed_at = datetime.now(timezone.utc)
    elif new_saved < Decimal(goal.target_amount) and goal.status == "completed":
        goal.status = "active"
        goal.completed_at = None

    audit_service.record(
        db,
        "GOAL_MOVEMENT_CREATED",
        tenant_id=user.tenant_id,
        user_id=user.id,
        entity="goal",
        entity_id=goal.id,
        details={"kind": data["kind"], "amount": f"{amount:.2f}"},
    )
    db.commit()
    return {
        "goal": _public(goal, new_saved, _today(db, user.tenant_id)),
        "movement": {
            "id": movement.id,
            "kind": movement.kind,
            "amount": movement.amount,
            "occurred_on": movement.occurred_on,
            "note": movement.note,
            "created_at": movement.created_at,
        },
    }


def list_movements(db: Session, tenant_id: uuid.UUID, goal_id: uuid.UUID) -> list[dict]:
    get_goal(db, tenant_id, goal_id)
    rows = db.scalars(
        select(GoalMovement)
        .where(GoalMovement.tenant_id == tenant_id, GoalMovement.goal_id == goal_id)
        .order_by(GoalMovement.occurred_on.desc(), GoalMovement.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "amount": row.amount,
            "occurred_on": row.occurred_on,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in rows
    ]
