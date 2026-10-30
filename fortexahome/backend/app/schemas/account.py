from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel


class AccountUpdate(APIModel):
    family_name: str | None = Field(default=None, min_length=1, max_length=120)
    currency: Literal["BRL"] | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    theme: Literal["claro", "escuro", "minimal"] | None = None
    name: str | None = Field(default=None, min_length=2, max_length=120)


class AccountPublic(APIModel):
    family_name: str
    currency: str
    timezone: str
    theme: str
    name: str
    email: str
