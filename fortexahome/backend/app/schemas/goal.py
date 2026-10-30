from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, PositiveMoney


class GoalCreate(APIModel):
    name: str = Field(min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=2000)
    target_amount: PositiveMoney
    target_date: date | None = None
    icon: str = Field(default="🎯", max_length=16)


class GoalUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=2000)
    target_amount: PositiveMoney | None = None
    target_date: date | None = None
    icon: str | None = Field(default=None, max_length=16)
    status: Literal["active", "completed", "cancelled"] | None = None


class GoalMovementCreate(APIModel):
    kind: Literal["deposit", "withdrawal"]
    amount: PositiveMoney
    occurred_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class GoalMovementPublic(APIModel):
    id: uuid.UUID
    kind: str
    amount: PositiveMoney
    occurred_on: date
    note: str | None
    created_at: datetime


class GoalPublic(APIModel):
    id: uuid.UUID
    name: str
    description: str | None
    target_amount: PositiveMoney
    target_date: date | None
    icon: str
    status: str
    saved_amount: str = "0.00"
    remaining_amount: str = "0.00"
    progress_percent: float = 0.0
    projected_monthly: str | None = None
    created_at: datetime
