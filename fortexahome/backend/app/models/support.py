from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin


class SupportOperator(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "support_operators"
    __table_args__ = (
        CheckConstraint("role IN ('support_read','support_operator')", name="ck_support_operators_role"),
        CheckConstraint("status IN ('active','disabled')", name="ck_support_operators_status"),
        Index("uq_support_operators_email_lookup_hash", "email_lookup_hash", unique=True),
    )

    email_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    email_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    email_masked: Mapped[str] = mapped_column(String(255), nullable=False)
    name_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="support_read")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportSession(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "support_sessions"
    __table_args__ = (
        Index("uq_support_sessions_token_hash", "token_hash", unique=True),
        Index("ix_support_sessions_operator_id", "operator_id"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("support_operators.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SupportAuditLog(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "support_audit_logs"
    __table_args__ = (
        Index("ix_support_audit_operator_created", "operator_id", "created_at"),
        Index("ix_support_audit_order", "order_id"),
        Index("ix_support_audit_license", "license_id"),
    )

    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("support_operators.id", ondelete="SET NULL"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    license_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
