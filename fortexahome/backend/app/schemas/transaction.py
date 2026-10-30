from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import APIModel, PositiveMoney


class TransactionCreate(APIModel):
    kind: Literal["income", "expense"]
    amount: PositiveMoney
    occurred_on: date
    description: str = Field(min_length=1, max_length=180)
    category_id: uuid.UUID | None = None
    payment_method: Literal["pix", "cash", "debit", "credit", "transfer", "boleto", "other"] = "pix"
    notes: str | None = Field(default=None, max_length=2000)
    card_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_card(self) -> "TransactionCreate":
        if self.card_id and self.payment_method != "credit":
            raise ValueError("Cartão só pode ser vinculado a lançamentos no crédito")
        return self


class TransactionUpdate(APIModel):
    kind: Literal["income", "expense"] | None = None
    amount: PositiveMoney | None = None
    occurred_on: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=180)
    category_id: uuid.UUID | None = None
    payment_method: Literal["pix", "cash", "debit", "credit", "transfer", "boleto", "other"] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    card_id: uuid.UUID | None = None


class TransactionPublic(APIModel):
    id: uuid.UUID
    kind: str
    amount: PositiveMoney
    occurred_on: date
    description: str
    category_id: uuid.UUID | None
    category_name: str | None = None
    payment_method: str
    notes: str | None
    card_id: uuid.UUID | None
    bill_id: uuid.UUID | None
    source: str
    created_at: datetime


class TransactionSummary(APIModel):
    income: str
    expense: str
    result: str
    count: int
