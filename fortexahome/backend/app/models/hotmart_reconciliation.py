from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDMixin


class HotmartReconciliationObservation(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "hotmart_reconciliation_observations"
    __table_args__ = (
        CheckConstraint(
            "comparison_result IN "
            "('consistent','correctable','manual_review','local_order_missing',"
            "'remote_not_found','stale','error')",
            name="ck_hotmart_reconciliation_comparison",
        ),
        CheckConstraint(
            "application_result IN ('no_change','applied','dry_run','rejected','failed')",
            name="ck_hotmart_reconciliation_application",
        ),
        UniqueConstraint(
            "run_id", "provider", "external_order_id",
            name="uq_hotmart_reconciliation_run_transaction",
        ),
        Index("ix_hotmart_reconciliation_order", "order_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, server_default="hotmart")
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="hotmart_sales_api")
    external_order_id: Mapped[str] = mapped_column(String(120), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    remote_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    remote_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_order_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    local_license_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    local_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comparison_result: Mapped[str] = mapped_column(String(32), nullable=False)
    application_result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    remote_order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_approved_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
