from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import APIModel


class SupportLoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class SupportOperatorPublic(APIModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None = None


class SupportAuthResponse(APIModel):
    operator: SupportOperatorPublic
    permissions: list[str]


class SupportRecoveryActionRequest(APIModel):
    justification: str = Field(min_length=10, max_length=500)

    @field_validator("justification")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("justificativa precisa ter pelo menos 10 caracteres")
        return value


class SupportOperatorProvision(APIModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    role: Literal["support_read", "support_operator"]
    password: str = Field(min_length=12, max_length=128)
    status: Literal["active", "disabled"] = "active"


class SupportPrivacyActionRequest(APIModel):
    justification: str = Field(min_length=10, max_length=500)

    @field_validator("justification")
    @classmethod
    def _strip_privacy(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("justificativa precisa ter pelo menos 10 caracteres")
        return value
