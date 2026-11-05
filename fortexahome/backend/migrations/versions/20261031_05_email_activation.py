"""Add isolated, short-lived activation challenges and preserve legacy users.

Revision ID: 20261031_05
Revises: 20261031_04
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings


revision: str = "20261031_05"
down_revision: Union[str, None] = "20261031_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_activations",
        sa.Column("license_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("license_code_hash", sa.String(length=64), nullable=False),
        sa.Column("email_encrypted", sa.Text(), nullable=False),
        sa.Column("email_lookup_hash", sa.String(length=64), nullable=False),
        sa.Column("name_encrypted", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("verification_code_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','consumed','expired','locked')", name="ck_pending_activations_status"
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 5", name="ck_pending_activations_attempts"),
        sa.ForeignKeyConstraint(["license_id"], ["licenses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_pending_activations_license_pending",
        "pending_activations",
        ["license_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_pending_activations_email_hash", "pending_activations", ["email_lookup_hash"])

    op.execute("ALTER TABLE pending_activations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pending_activations FORCE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY pending_activation_by_id ON pending_activations FOR SELECT
        USING (id = NULLIF(current_setting('app.pending_activation_id', true), '')::uuid)"""
    )
    op.execute(
        """CREATE POLICY pending_activation_by_license ON pending_activations FOR SELECT
        USING (EXISTS (SELECT 1 FROM licenses l WHERE l.id = pending_activations.license_id))"""
    )
    op.execute(
        """CREATE POLICY pending_activation_insert ON pending_activations FOR INSERT
        WITH CHECK (
          status = 'pending' AND attempt_count = 0 AND consumed_at IS NULL
          AND EXISTS (SELECT 1 FROM licenses l WHERE l.id = pending_activations.license_id)
        )"""
    )
    op.execute(
        """CREATE POLICY pending_activation_update ON pending_activations FOR UPDATE
        USING (id = NULLIF(current_setting('app.pending_activation_id', true), '')::uuid)
        WITH CHECK (id = NULLIF(current_setting('app.pending_activation_id', true), '')::uuid)"""
    )

    role = get_settings().APP_DB_USER
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", role):
        raise ValueError("APP_DB_USER deve ser um identificador PostgreSQL simples")
    op.execute(f"REVOKE ALL ON pending_activations FROM {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON pending_activations TO {role}")

    # The dedicated migration role performs this one-time compatibility backfill;
    # RLS remains enabled and forced throughout the migration.
    op.execute("SET LOCAL row_security = off")
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")


def downgrade() -> None:
    op.execute("DROP POLICY pending_activation_update ON pending_activations")
    op.execute("DROP POLICY pending_activation_insert ON pending_activations")
    op.execute("DROP POLICY pending_activation_by_license ON pending_activations")
    op.execute("DROP POLICY pending_activation_by_id ON pending_activations")
    op.drop_index("ix_pending_activations_email_hash", table_name="pending_activations")
    op.drop_index("uq_pending_activations_license_pending", table_name="pending_activations")
    op.drop_table("pending_activations")

