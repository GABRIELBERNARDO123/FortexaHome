from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel


class CategoryCreate(APIModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["income", "expense"]
    color: str = Field(default="#ffa400", pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str = Field(default="tag", max_length=32)


class CategoryUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, max_length=32)
    archived: bool | None = None


class CategoryPublic(APIModel):
    id: uuid.UUID
    name: str
    kind: str
    color: str
    icon: str
    is_system: bool
    archived: bool
    usage_count: int
    in_use: bool
