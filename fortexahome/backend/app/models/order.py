from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin


class Order(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','paid','refunded','chargeback','cancelled')",
            name="ck_orders_status",
        ),
        UniqueConstraint("provider", "external_order_id", name="uq_orders_provider_external"),
        Index("ix_orders_buyer_email_hash", "buyer_email_hash"),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False, server_default="hmac_sandbox")
    external_order_id: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    buyer_email_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_email_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="BRL")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    external_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
