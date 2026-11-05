"""Track bounded outbox recovery and validate reset tokens before delivery.

Revision ID: 20261031_07
Revises: 20261031_06
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.config import get_settings

revision: str = "20261031_07"
down_revision: Union[str, None] = "20261031_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    settings = get_settings()
    for name in (settings.APP_DB_USER, settings.OUTBOX_DB_USER):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name):
            raise ValueError("Os papéis PostgreSQL devem usar identificadores simples")
    prep = op.get_bind().dialect.identifier_preparer
    app_role = prep.quote(settings.APP_DB_USER)
    worker_role = prep.quote(settings.OUTBOX_DB_USER)

    op.add_column(
        "email_outbox",
        sa.Column("manual_requeue_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("email_outbox", sa.Column("last_requeued_at", sa.DateTime(timezone=True)))
    op.add_column("email_outbox", sa.Column("last_requeued_by", sa.String(128)))
    op.create_check_constraint(
        "ck_email_outbox_manual_requeue_count",
        "email_outbox",
        "manual_requeue_count BETWEEN 0 AND 1",
    )

    # Add narrow policies without changing the existing tenant/reset policies.
    op.execute(
        f"CREATE POLICY email_outbox_app_reset_cancel ON email_outbox FOR UPDATE TO {app_role} "
        "USING (event_type = 'password_reset' "
        "AND aggregate_id = NULLIF(current_setting('app.password_reset_token_id', true), '')::uuid "
        "AND status IN ('pending','processing')) "
        "WITH CHECK (event_type = 'password_reset' "
        "AND aggregate_id = NULLIF(current_setting('app.password_reset_token_id', true), '')::uuid "
        "AND status = 'cancelled')"
    )
    op.execute(
        f"CREATE POLICY email_outbox_worker_reset_status ON password_reset_tokens FOR SELECT TO {worker_role} "
        "USING (id = NULLIF(current_setting('app.outbox_reset_token_id', true), '')::uuid)"
    )
    op.execute(f"REVOKE ALL ON password_reset_tokens FROM {worker_role}")
    op.execute(f"GRANT SELECT (id, used_at, expires_at) ON password_reset_tokens TO {worker_role}")


def downgrade() -> None:
    settings = get_settings()
    worker_role = op.get_bind().dialect.identifier_preparer.quote(settings.OUTBOX_DB_USER)
    op.execute("DROP POLICY IF EXISTS email_outbox_worker_reset_status ON password_reset_tokens")
    op.execute("DROP POLICY IF EXISTS email_outbox_app_reset_cancel ON email_outbox")
    op.execute(f"REVOKE SELECT (id, used_at, expires_at) ON password_reset_tokens FROM {worker_role}")
    op.drop_constraint("ck_email_outbox_manual_requeue_count", "email_outbox", type_="check")
    op.drop_column("email_outbox", "last_requeued_by")
    op.drop_column("email_outbox", "last_requeued_at")
    op.drop_column("email_outbox", "manual_requeue_count")
