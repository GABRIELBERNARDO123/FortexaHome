"""Add distributed progressive account login lockout.

Revision ID: 20261102_16
Revises: 20261102_15
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.config import get_settings


revision: str = "20261102_16"
down_revision: Union[str, None] = "20261102_15"
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
        "login_lockout_states",
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("failure_count >= 0", name="ck_login_lockout_failure_count"),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_index("ix_login_lockout_expires_at", "login_lockout_states", ["expires_at"])
    op.execute(f"REVOKE ALL ON login_lockout_states FROM PUBLIC, {app_ident}, {worker_ident}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON login_lockout_states TO {app_ident}")


def downgrade() -> None:
    op.drop_index("ix_login_lockout_expires_at", table_name="login_lockout_states")
    op.drop_table("login_lockout_states")
