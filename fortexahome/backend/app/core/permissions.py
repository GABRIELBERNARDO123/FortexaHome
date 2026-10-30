from __future__ import annotations

from fastapi import HTTPException, status

from app.models.user import User

PROFILE_GRANTS: dict[str, frozenset[str]] = {
    "owner": frozenset({"*"}),
    "member": frozenset(
        {
            "finance:read",
            "finance:write",
            "goals:read",
            "goals:write",
            "reports:read",
            "account:read",
        }
    ),
}


def can(user: User, permission: str) -> bool:
    grants = PROFILE_GRANTS.get(user.role, frozenset())
    return "*" in grants or permission in grants


def require_permission(user: User, permission: str) -> None:
    if not can(user, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não tem permissão para esta ação")


def require_owner(user: User) -> None:
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o responsável pela conta pode fazer isso")
