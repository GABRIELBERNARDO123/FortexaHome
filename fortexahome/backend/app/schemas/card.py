from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import Field

from app.schemas.common import APIModel, NonNegativeMoney, NonNegativeMoney as NNMoney


class CardCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    institution: str = Field(min_length=1, max_length=100)
    limit_amount: NonNegativeMoney
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)


class CardUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    institution: str | None = Field(default=None, min_length=1, max_length=100)
    limit_amount: NonNegativeMoney | None = None
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)
    archived: bool | None = None


class CardPublic(APIModel):
    id: uuid.UUID
    name: str
    institution: str
    limit_amount: NonNegativeMoney
    closing_day: int
    due_day: int
    archived: bool
    spent: str = "0.00"
    available: str = "0.00"
