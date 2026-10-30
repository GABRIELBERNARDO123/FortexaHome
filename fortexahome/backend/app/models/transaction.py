from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin


class Transaction(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("kind IN ('income','expense')", name="ck_transactions_kind"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "payment_method IN ('pix','cash','debit','credit','transfer','boleto','other')",
            name="ck_transactions_payment_method",
        ),
        CheckConstraint("source IN ('manual','bill','import')", name="ck_transactions_source"),
        Index("ix_transactions_tenant_date", "tenant_id", "occurred_on"),
        Index("ix_transactions_tenant_category", "tenant_id", "category_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(180), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pix")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True
    )
    bill_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bills.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual")
