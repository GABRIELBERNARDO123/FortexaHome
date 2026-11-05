from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import APIModel


class PrivacyRequestCreate(APIModel):
    password: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class PrivacyRequestPublic(APIModel):
    id: uuid.UUID
    protocol: str
    request_type: str
    status: str
    scope: str
    reason: str | None = None
    retention_summary: dict | None = None
    result_summary: str | None = None
    review_justification: str | None = None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class PrivacyRequestEventPublic(APIModel):
    id: uuid.UUID
    event_type: str
    status: str | None = None
    actor_type: str
    details: dict | None = None
    created_at: datetime


class PrivacyRequestDetail(PrivacyRequestPublic):
    events: list[PrivacyRequestEventPublic] = []
