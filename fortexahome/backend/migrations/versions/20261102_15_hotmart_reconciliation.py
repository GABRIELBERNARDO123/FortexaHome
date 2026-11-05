"""Add immutable Hotmart reconciliation observations.

Revision ID: 20261102_15
Revises: 20261102_14
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings


revision: str = "20261102_15"
down_revision: Union[str, None] = "20261102_14"
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
        "hotmart_reconciliation_observations",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), server_default="hotmart", nullable=False),
        sa.Column("source", sa.String(32), server_default="hotmart_sales_api", nullable=False),
        sa.Column("external_order_id", sa.String(120), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("remote_status", sa.String(40), nullable=True),
        sa.Column("remote_product_id", sa.Integer(), nullable=True),
        sa.Column("local_order_status", sa.String(16), nullable=True),
        sa.Column("local_license_status", sa.String(16), nullable=True),
        sa.Column("local_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comparison_result", sa.String(32), nullable=False),
        sa.Column("application_result", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("remote_order_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_approved_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "comparison_result IN "
            "('consistent','correctable','manual_review','local_order_missing',"
            "'remote_not_found','stale','error')",
            name="ck_hotmart_reconciliation_comparison",
        ),
        sa.CheckConstraint(
            "application_result IN ('no_change','applied','dry_run','rejected','failed')",
            name="ck_hotmart_reconciliation_application",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "provider", "external_order_id",
            name="uq_hotmart_reconciliation_run_transaction",
        ),
    )
    op.create_index(
        "ix_hotmart_reconciliation_order",
        "hotmart_reconciliation_observations",
        ["order_id"],
    )
    op.execute(
        f"REVOKE ALL ON hotmart_reconciliation_observations FROM PUBLIC, {app_ident}, {worker_ident}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON hotmart_reconciliation_observations TO {app_ident}"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hotmart_reconciliation_order",
        table_name="hotmart_reconciliation_observations",
    )
    op.drop_table("hotmart_reconciliation_observations")
