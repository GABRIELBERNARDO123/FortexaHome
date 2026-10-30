from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin


class Product(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("license_kind IN ('lifetime','subscription')", name="ck_products_license_kind"),
        CheckConstraint("price_cents >= 0", name="ck_products_price"),
        Index("uq_products_slug", "slug", unique=True),
    )

    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="BRL")
    license_kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="lifetime")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
