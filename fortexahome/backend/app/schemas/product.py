from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import APIModel


class ProductProvision(APIModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price_cents: int = Field(ge=0, le=2_147_483_647)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    license_kind: Literal["lifetime", "subscription"]
    active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("nome não pode ser vazio")
        return value

    @field_validator("description")
    @classmethod
    def _description_normalized(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None
