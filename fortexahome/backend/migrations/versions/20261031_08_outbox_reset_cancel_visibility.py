"""Allow the app to see only reset-mail metadata it may cancel.

Revision ID: 20261031_08
Revises: 20261031_07
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op

from app.core.config import get_settings

revision: str = "20261031_08"
down_revision: Union[str, None] = "20261031_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    app_role = get_settings().APP_DB_USER
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", app_role):
        raise ValueError("APP_DB_USER deve usar um identificador PostgreSQL simples")
    role = op.get_bind().dialect.identifier_preparer.quote(app_role)
    op.execute(
        f"CREATE POLICY email_outbox_app_reset_metadata ON email_outbox FOR SELECT TO {role} "
        "USING (event_type = 'password_reset' "
        "AND aggregate_id = NULLIF(current_setting('app.password_reset_token_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS email_outbox_app_reset_metadata ON email_outbox")
