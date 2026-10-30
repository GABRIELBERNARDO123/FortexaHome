from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, PositiveMoney


class BillCreate(APIModel):
    name: str = Field(min_length=1, max_length=160)
    category_id: uuid.UUID | None = None
    amount: PositiveMoney
    due_on: date
    recurrence: Literal["none", "monthly"] = "none"
    notes: str | None = Field(default=None, max_length=2000)


class BillUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category_id: uuid.UUID | None = None
    amount: PositiveMoney | None = None
    due_on: date | None = None
    recurrence: Literal["none", "monthly"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class BillPublic(APIModel):
    id: uuid.UUID
    name: str
    category_id: uuid.UUID | None
    category_name: str | None = None
    amount: PositiveMoney
    due_on: date
    status: str
    paid_at: datetime | None
    recurrence: str
    parent_bill_id: uuid.UUID | None
    notes: str | None
    transaction_id: uuid.UUID | None = None
    is_overdue: bool = False
