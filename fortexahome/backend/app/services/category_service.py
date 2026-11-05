from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bill import Bill
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service


def _usage_counts(db: Session, tenant_id: uuid.UUID, category_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not category_ids:
        return {}
    counts: defaultdict[uuid.UUID, int] = defaultdict(int)
    for model in (Transaction, Bill, Budget):
        rows = db.execute(
            select(model.category_id, func.count(model.id))
            .where(model.tenant_id == tenant_id, model.category_id.in_(category_ids))
            .group_by(model.category_id)
        ).all()
        for category_id, count in rows:
            if category_id is not None:
                counts[category_id] += count
    return dict(counts)


def _public(row: Category, usage_count: int = 0) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "color": row.color,
        "icon": row.icon,
        "is_system": row.is_system,
        "archived": row.archived,
        "usage_count": usage_count,
        "in_use": usage_count > 0,
    }


def list_categories(
    db: Session,
    tenant_id: uuid.UUID,
    kind: str | None = None,
    archived: bool | None = None,
) -> list[dict]:
    query = select(Category).where(Category.tenant_id == tenant_id)
    if kind:
        query = query.where(Category.kind == kind)
    if archived is not None:
        query = query.where(Category.archived == archived)
    rows = db.scalars(query.order_by(Category.kind, Category.archived, Category.name)).all()
    counts = _usage_counts(db, tenant_id, [row.id for row in rows])
    return [_public(row, counts.get(row.id, 0)) for row in rows]


def get_category(db: Session, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    row = db.scalar(select(Category).where(Category.id == category_id, Category.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria não encontrada")
    return row


def _name_exists(db: Session, tenant_id: uuid.UUID, kind: str, name: str, ignore_id: uuid.UUID | None = None) -> bool:
    query = select(Category.id).where(
        Category.tenant_id == tenant_id,
        Category.kind == kind,
        func.lower(Category.name) == name.strip().lower(),
    )
    if ignore_id:
        query = query.where(Category.id != ignore_id)
    return db.scalar(query) is not None


def create_category(db: Session, user: User, *, name: str, kind: str, color: str, icon: str) -> dict:
    if _name_exists(db, user.tenant_id, kind, name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma categoria com este nome")
    row = Category(
        tenant_id=user.tenant_id,
        name=name.strip(),
        kind=kind,
        color=color,
        icon=icon,
        is_system=False,
    )
    db.add(row)
    db.flush()
    audit_service.record(
        db, "CATEGORY_CREATED", tenant_id=user.tenant_id, user_id=user.id, entity="category", entity_id=row.id
    )
    db.commit()
    return _public(row)


def update_category(db: Session, user: User, category_id: uuid.UUID, data: dict) -> dict:
    row = get_category(db, user.tenant_id, category_id)
    if "name" in data and data["name"] is not None:
        if _name_exists(db, user.tenant_id, row.kind, data["name"], ignore_id=row.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma categoria com este nome")
        row.name = data["name"].strip()
    if data.get("color"):
        row.color = data["color"]
    if data.get("icon"):
        row.icon = data["icon"]

    archived_changed = False
    if data.get("archived") is not None and data["archived"] != row.archived:
        if data["archived"] and row.is_system:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Categorias padrão não podem ser arquivadas",
            )
        row.archived = data["archived"]
        archived_changed = True

    if archived_changed:
        operation = "CATEGORY_ARCHIVED" if row.archived else "CATEGORY_REACTIVATED"
    else:
        operation = "CATEGORY_UPDATED"
    audit_service.record(
        db, operation, tenant_id=user.tenant_id, user_id=user.id, entity="category", entity_id=row.id
    )
    db.commit()
    usage_count = _usage_counts(db, user.tenant_id, [row.id]).get(row.id, 0)
    return _public(row, usage_count)


def delete_category(db: Session, user: User, category_id: uuid.UUID) -> None:
    row = get_category(db, user.tenant_id, category_id)
    if row.is_system:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Categorias padrão não podem ser excluídas")
    if _usage_counts(db, user.tenant_id, [category_id]).get(category_id, 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Categoria em uso. Arquive-a ou altere os lançamentos antes de excluir.",
        )
    db.delete(row)
    audit_service.record(
        db, "CATEGORY_DELETED", tenant_id=user.tenant_id, user_id=user.id, entity="category", entity_id=category_id
    )
    db.commit()
