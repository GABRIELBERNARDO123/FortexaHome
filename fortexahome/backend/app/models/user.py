from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UpdatedAtMixin, UUIDMixin


class User(UUIDMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner','member')", name="ck_users_role"),
        CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
        CheckConstraint("theme IN ('claro','escuro','minimal')", name="ck_users_theme"),
        Index("uq_users_email_lookup_hash", "email_lookup_hash", unique=True),
        Index("ix_users_tenant_id", "tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    email_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    email_masked: Mapped[str] = mapped_column(String(255), nullable=False)
    name_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="owner")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    theme: Mapped[str] = mapped_column(String(16), nullable=False, server_default="claro")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
