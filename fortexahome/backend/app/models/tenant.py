from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin
from app.core.database import Base


class Tenant(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("char_length(currency) = 3", name="ck_tenants_currency"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="BRL")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="America/Sao_Paulo")
