from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin

REQUEST_TYPES = (
    "erasure",
    "access",
    "correction",
    "anonymization",
    "blocking",
    "portability",
    "information",
)
REQUEST_STATUSES = (
    "submitted",
    "awaiting_review",
    "approved",
    "processing",
    "completed",
    "partially_completed",
    "rejected",
    "cancelled",
)
TERMINAL_STATUSES = ("completed", "partially_completed", "rejected", "cancelled")


class PrivacyRequest(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('erasure','access','correction','anonymization','blocking','portability','information')",
            name="ck_privacy_requests_type",
        ),
        CheckConstraint(
            "status IN ('submitted','awaiting_review','approved','processing','completed',"
            "'partially_completed','rejected','cancelled')",
            name="ck_privacy_requests_status",
        ),
        CheckConstraint("scope IN ('user','tenant')", name="ck_privacy_requests_scope"),
        Index("uq_privacy_requests_protocol", "protocol", unique=True),
        Index("ix_privacy_requests_tenant_created", "tenant_id", "created_at"),
        Index("ix_privacy_requests_user_created", "user_id", "created_at"),
        Index(
            "uq_privacy_requests_active_erasure",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where=(
                "request_type = 'erasure' AND status IN "
                "('submitted','awaiting_review','approved','processing')"
            ),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="submitted")
    scope: Mapped[str] = mapped_column(String(16), nullable=False, server_default="user")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_method: Mapped[str] = mapped_column(String(32), nullable=False, server_default="password")
    retention_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("support_operators.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PrivacyRequestEvent(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "privacy_request_events"
    __table_args__ = (
        Index("ix_privacy_request_events_request", "request_id", "created_at"),
        Index("ix_privacy_request_events_tenant", "tenant_id", "created_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("privacy_requests.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class DataDeletionTombstone(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "data_deletion_tombstones"
    __table_args__ = (
        CheckConstraint("scope IN ('user','tenant')", name="ck_data_deletion_tombstones_scope"),
        Index("ix_data_deletion_tombstones_tenant", "tenant_id", "created_at"),
        Index("ix_data_deletion_tombstones_user", "user_id"),
    )

    request_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("privacy_requests.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
