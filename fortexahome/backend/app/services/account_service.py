from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.field_encryption import decrypt_text, encrypt_text
from app.core.permissions import require_owner
from app.models.tenant import Tenant
from app.models.user import User
from app.services import audit_service


def account_payload(db: Session, user: User) -> dict:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada")
    return {
        "family_name": tenant.name,
        "currency": tenant.currency,
        "timezone": tenant.timezone,
        "theme": user.theme,
        "name": decrypt_text(user.name_encrypted, "users.name") or "",
        "email": decrypt_text(user.email_encrypted, "users.email") or "",
    }


def update_account(db: Session, user: User, data: dict) -> dict:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada")

    if "family_name" in data:
        require_owner(user)
        if data["family_name"] is not None:
            tenant.name = data["family_name"].strip()
    if "currency" in data and data["currency"] is not None:
        require_owner(user)
        tenant.currency = data["currency"]
    if "timezone" in data and data["timezone"] is not None:
        require_owner(user)
        try:
            ZoneInfo(data["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Fuso horário inválido"
            ) from exc
        tenant.timezone = data["timezone"]
    if "name" in data and data["name"] is not None:
        user.name_encrypted = encrypt_text(data["name"].strip(), "users.name")
    if "theme" in data and data["theme"] is not None:
        user.theme = data["theme"]

    audit_service.record(
        db, "ACCOUNT_UPDATED", tenant_id=user.tenant_id, user_id=user.id, entity="tenant", entity_id=tenant.id
    )
    db.commit()
    return account_payload(db, user)
