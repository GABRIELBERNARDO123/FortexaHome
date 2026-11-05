from __future__ import annotations

from pydantic import EmailStr, Field

from app.schemas.common import APIModel


class RecoverLicenseRequest(APIModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RecoverLicenseConfirmRequest(APIModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class RecoveryMessage(APIModel):
    message: str
