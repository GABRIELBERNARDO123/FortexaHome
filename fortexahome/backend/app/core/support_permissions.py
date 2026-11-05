from __future__ import annotations

from fastapi import HTTPException, status

from app.models.support import SupportOperator

SUPPORT_GRANTS: dict[str, frozenset[str]] = {
    "support_read": frozenset({"support:read"}),
    "support_operator": frozenset({"support:read", "support:act"}),
}


def support_can(operator: SupportOperator, permission: str) -> bool:
    return permission in SUPPORT_GRANTS.get(operator.role, frozenset())


def require_support_permission(operator: SupportOperator, permission: str) -> None:
    if not support_can(operator, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu perfil de suporte não permite esta operação",
        )
