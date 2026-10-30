from __future__ import annotations

import uuid
from datetime import date

from pydantic import Field, model_validator

from app.schemas.common import APIModel, PositiveMoney


class BudgetCreate(APIModel):
    category_id: uuid.UUID
    competence_month: date
    limit_amount: PositiveMoney

    @model_validator(mode="after")
    def first_day(self) -> "BudgetCreate":
        if self.competence_month.day != 1:
            raise ValueError("competence_month deve ser o primeiro dia do mês")
        return self


class BudgetUpdate(APIModel):
    limit_amount: PositiveMoney


class BudgetPublic(APIModel):
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str | None = None
    competence_month: date
    limit_amount: PositiveMoney
    spent: str = "0.00"
    available: str = "0.00"
    percent: float = 0.0
