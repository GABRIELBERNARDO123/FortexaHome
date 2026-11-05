from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin


class PendingActivation(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "pending_activations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','consumed','expired','locked')",
            name="ck_pending_activations_status",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 5", name="ck_pending_activations_attempts"),
        Index(
            "uq_pending_activations_license_pending",
            "license_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_pending_activations_email_hash", "email_lookup_hash"),
    )

    license_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("licenses.id", ondelete="CASCADE"), nullable=False
    )
    license_code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    email_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    email_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    verification_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

