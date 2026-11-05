from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import APIModel


class ActivateRequest(APIModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    license_code: str = Field(min_length=4, max_length=40)

    @field_validator("name", "license_code")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ActivationCodeRequest(APIModel):
    activation_id: uuid.UUID
    code: str = Field(pattern=r"^\d{6}$")


class ActivationResendRequest(APIModel):
    activation_id: uuid.UUID


class ActivationStartResponse(APIModel):
    activation_id: uuid.UUID
    email_masked: str
    expires_at: datetime | None
    resend_at: datetime


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(APIModel):
    email: EmailStr


class ResetPasswordRequest(APIModel):
    token: str = Field(min_length=16, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(APIModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TenantPublic(APIModel):
    id: uuid.UUID
    name: str
    currency: str
    timezone: str


class LicensePublic(APIModel):
    id: uuid.UUID
    status: str
    code_last4: str
    kind: str = "lifetime"
    activated_at: datetime | None = None
    expires_at: datetime | None = None


class UserPublic(APIModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    theme: str
    created_at: datetime


class AuthResponse(APIModel):
    user: UserPublic
    tenant: TenantPublic
    license: LicensePublic
