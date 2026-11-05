from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDMixin


class EmailOutbox(UUIDMixin, CreatedAtMixin, Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        Index("uq_email_outbox_idempotency_key", "idempotency_key", unique=True),
        Index("ix_email_outbox_due", "status", "next_attempt_at", "created_at"),
        Index("ix_email_outbox_aggregate", "aggregate_id", "event_type", "status"),
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    payload_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Client default avoids widening app-role SELECT grants just to satisfy
    # INSERT ... RETURNING for this worker-owned audit field.
    manual_requeue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_requeued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_requeued_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
