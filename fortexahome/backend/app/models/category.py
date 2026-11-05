from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin


class Category(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("kind IN ('income','expense')", name="ck_categories_kind"),
        Index("uq_categories_tenant_kind_name", "tenant_id", "kind", text("lower(name)"), unique=True),
        Index("ix_categories_tenant_id", "tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False, server_default="#ffa400")
    icon: Mapped[str] = mapped_column(String(32), nullable=False, server_default="tag")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
