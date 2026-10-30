from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bill import Bill
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.services import audit_service


def list_categories(db: Session, tenant_id: uuid.UUID, kind: str | None = None) -> list[dict]:
    query = select(Category).where(Category.tenant_id == tenant_id)
    if kind:
        query = query.where(Category.kind == kind)
    rows = db.scalars(query.order_by(Category.kind, Category.name)).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "color": row.color,
            "icon": row.icon,
            "is_system": row.is_system,
        }
        for row in rows
    ]


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
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "color": row.color,
        "icon": row.icon,
        "is_system": row.is_system,
    }


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
    audit_service.record(
        db, "CATEGORY_UPDATED", tenant_id=user.tenant_id, user_id=user.id, entity="category", entity_id=row.id
    )
    db.commit()
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "color": row.color,
        "icon": row.icon,
        "is_system": row.is_system,
    }


def delete_category(db: Session, user: User, category_id: uuid.UUID) -> None:
    row = get_category(db, user.tenant_id, category_id)
    if row.is_system:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Categorias padrão não podem ser excluídas")
    in_use = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.tenant_id == user.tenant_id, Transaction.category_id == category_id)
    )
    in_bills = db.scalar(
        select(func.count()).select_from(Bill).where(Bill.tenant_id == user.tenant_id, Bill.category_id == category_id)
    )
    in_budgets = db.scalar(
        select(func.count()).select_from(Budget).where(Budget.tenant_id == user.tenant_id, Budget.category_id == category_id)
    )
    if (in_use or 0) + (in_bills or 0) + (in_budgets or 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Categoria em uso. Altere os lançamentos ou orçamentos antes de excluir.",
        )
    db.delete(row)
    audit_service.record(
        db, "CATEGORY_DELETED", tenant_id=user.tenant_id, user_id=user.id, entity="category", entity_id=category_id
    )
    db.commit()
