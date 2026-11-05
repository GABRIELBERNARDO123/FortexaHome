"""Add financial operation idempotency records.

Revision ID: 20261104_17
Revises: 20261102_16
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings


revision: str = "20261104_17"
down_revision: Union[str, None] = "20261102_16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _roles() -> tuple[str, str]:
    settings = get_settings()
    for name in (settings.APP_DB_USER, settings.OUTBOX_DB_USER):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name):
            raise ValueError("Os papéis PostgreSQL devem usar identificadores simples")
    if settings.APP_DB_USER == settings.OUTBOX_DB_USER:
        raise ValueError("O papel operacional e o worker da outbox devem ser diferentes")
    return settings.APP_DB_USER, settings.OUTBOX_DB_USER


def upgrade() -> None:
    app_role, worker_role = _roles()
    preparer = op.get_bind().dialect.identifier_preparer
    app_ident = preparer.quote(app_role)
    worker_ident = preparer.quote(worker_role)

    op.create_table(
        "idempotency_records",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="processing", nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('processing','completed')", name="ck_idempotency_status"),
        sa.CheckConstraint("length(key_hash) = 64", name="ck_idempotency_key_hash_length"),
        sa.CheckConstraint("length(fingerprint) = 64", name="ck_idempotency_fingerprint_length"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "operation",
            "key_hash",
            name="uq_idempotency_scope_key",
        ),
    )
    op.create_index("ix_idempotency_expires_at", "idempotency_records", ["expires_at"])
    op.create_index(
        "ix_idempotency_scope_created",
        "idempotency_records",
        ["tenant_id", "user_id", "created_at"],
    )

    op.execute("ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_records FORCE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON idempotency_records FROM PUBLIC, {app_ident}, {worker_ident}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON idempotency_records TO {app_ident} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_records TO {app_ident}")


def downgrade() -> None:
    app_role, _ = _roles()
    preparer = op.get_bind().dialect.identifier_preparer
    app_ident = preparer.quote(app_role)

    op.execute(f"REVOKE ALL ON idempotency_records FROM {app_ident}")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON idempotency_records")
    op.drop_index("ix_idempotency_scope_created", table_name="idempotency_records")
    op.drop_index("ix_idempotency_expires_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
