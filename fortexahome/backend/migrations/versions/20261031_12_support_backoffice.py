"""Add support operators, sessions, audit and scoped administrative reads.

Revision ID: 20261031_12
Revises: 20261031_11
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings


revision: str = "20261031_12"
down_revision: Union[str, None] = "20261031_11"
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
        "support_operators",
        sa.Column("email_encrypted", sa.Text(), nullable=False),
        sa.Column("email_lookup_hash", sa.String(64), nullable=False),
        sa.Column("email_masked", sa.String(255), nullable=False),
        sa.Column("name_encrypted", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), server_default="support_read", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('support_read','support_operator')", name="ck_support_operators_role"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_support_operators_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_support_operators_email_lookup_hash",
        "support_operators",
        ["email_lookup_hash"],
        unique=True,
    )

    op.create_table(
        "support_sessions",
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["support_operators.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_support_sessions_token_hash", "support_sessions", ["token_hash"], unique=True)
    op.create_index("ix_support_sessions_operator_id", "support_sessions", ["operator_id"])

    op.create_table(
        "support_audit_logs",
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("license_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["support_operators.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_audit_operator_created", "support_audit_logs", ["operator_id", "created_at"])
    op.create_index("ix_support_audit_order", "support_audit_logs", ["order_id"])
    op.create_index("ix_support_audit_license", "support_audit_logs", ["license_id"])

    for table in ("support_operators", "support_sessions", "support_audit_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM {app_ident}, {worker_ident}")

    op.execute(
        f"CREATE POLICY support_operator_login ON support_operators FOR SELECT TO {app_ident} "
        "USING (status = 'active' "
        "AND email_lookup_hash = NULLIF(current_setting('app.support_login_email_hash', true), ''))"
    )
    op.execute(
        f"CREATE POLICY support_operator_self ON support_operators FOR SELECT TO {app_ident} "
        "USING (id = NULLIF(current_setting('app.support_operator_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY support_operator_login_update ON support_operators FOR UPDATE TO {app_ident} "
        "USING (email_lookup_hash = NULLIF(current_setting('app.support_login_email_hash', true), '')) "
        "WITH CHECK (email_lookup_hash = NULLIF(current_setting('app.support_login_email_hash', true), ''))"
    )
    op.execute(
        f"CREATE POLICY support_operator_provision_select ON support_operators FOR SELECT TO {app_ident} "
        "USING (current_setting('app.support_provisioning', true) = 'true')"
    )
    op.execute(
        f"CREATE POLICY support_operator_provision_insert ON support_operators FOR INSERT TO {app_ident} "
        "WITH CHECK (current_setting('app.support_provisioning', true) = 'true')"
    )
    op.execute(
        f"CREATE POLICY support_operator_provision_update ON support_operators FOR UPDATE TO {app_ident} "
        "USING (current_setting('app.support_provisioning', true) = 'true') "
        "WITH CHECK (current_setting('app.support_provisioning', true) = 'true')"
    )

    op.execute(
        f"CREATE POLICY support_session_lookup ON support_sessions FOR SELECT TO {app_ident} "
        "USING (token_hash = NULLIF(current_setting('app.support_session_token_hash', true), ''))"
    )
    op.execute(
        f"CREATE POLICY support_session_self_select ON support_sessions FOR SELECT TO {app_ident} "
        "USING (operator_id = NULLIF(current_setting('app.support_operator_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY support_session_self_update ON support_sessions FOR UPDATE TO {app_ident} "
        "USING (operator_id = NULLIF(current_setting('app.support_operator_id', true), '')::uuid) "
        "WITH CHECK (operator_id = NULLIF(current_setting('app.support_operator_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY support_session_insert ON support_sessions FOR INSERT TO {app_ident} "
        "WITH CHECK (operator_id = NULLIF(current_setting('app.support_operator_id', true), '')::uuid)"
    )

    op.execute(
        f"CREATE POLICY support_audit_insert ON support_audit_logs FOR INSERT TO {app_ident} "
        "WITH CHECK (operator_id = NULLIF(current_setting('app.support_operator_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY support_audit_select ON support_audit_logs FOR SELECT TO {app_ident} "
        "USING (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
    )

    for table in ("orders", "payment_events", "licenses"):
        op.execute(
            f"CREATE POLICY support_{table}_read ON {table} FOR SELECT TO {app_ident} "
            "USING (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
        )
    op.execute(
        f"CREATE POLICY support_email_outbox_read ON email_outbox FOR SELECT TO {app_ident} "
        "USING (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
    )

    op.execute(
        f"CREATE POLICY pending_activation_recovery_by_email ON pending_activations FOR SELECT TO {app_ident} "
        "USING (email_lookup_hash = NULLIF(current_setting('app.pending_recovery_email_hash', true), ''))"
    )
    op.execute(
        f"CREATE POLICY orders_license_recovery ON orders FOR SELECT TO {app_ident} "
        "USING (buyer_email_hash = NULLIF(current_setting('app.license_recovery_email_hash', true), '') "
        "AND provider = NULLIF(current_setting('app.payment_provider', true), ''))"
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON support_operators TO {app_ident}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON support_sessions TO {app_ident}")
    op.execute(f"GRANT SELECT, INSERT ON support_audit_logs TO {app_ident}")
    op.execute(
        f"GRANT SELECT (id, idempotency_key, attempt_count, max_attempts, next_attempt_at, "
        f"processed_at, sent_at, last_error, created_at) ON email_outbox TO {app_ident}"
    )

    op.drop_constraint("ck_email_outbox_event_type", "email_outbox", type_="check")
    op.create_check_constraint(
        "ck_email_outbox_event_type",
        "email_outbox",
        "event_type IN ('activation_verification','password_reset','license_delivery','license_recovery_instructions')",
    )


def downgrade() -> None:
    app_role, _ = _roles()
    preparer = op.get_bind().dialect.identifier_preparer
    app_ident = preparer.quote(app_role)

    # Keep the event-type constraint broad on downgrade so existing
    # license_recovery_instructions audit rows are preserved. The table itself
    # is dropped by the historical outbox downgrade (20261031_06) when needed.

    op.execute("DROP POLICY IF EXISTS orders_license_recovery ON orders")
    op.execute("DROP POLICY IF EXISTS pending_activation_recovery_by_email ON pending_activations")
    op.execute("DROP POLICY IF EXISTS support_email_outbox_read ON email_outbox")
    for table in ("orders", "payment_events", "licenses"):
        op.execute(f"DROP POLICY IF EXISTS support_{table}_read ON {table}")

    op.execute(f"REVOKE SELECT (id, idempotency_key, attempt_count, max_attempts, next_attempt_at, "
               f"processed_at, sent_at, last_error, created_at) ON email_outbox FROM {app_ident}")

    op.drop_index("ix_support_audit_license", table_name="support_audit_logs")
    op.drop_index("ix_support_audit_order", table_name="support_audit_logs")
    op.drop_index("ix_support_audit_operator_created", table_name="support_audit_logs")
    op.drop_table("support_audit_logs")
    op.drop_index("ix_support_sessions_operator_id", table_name="support_sessions")
    op.drop_index("uq_support_sessions_token_hash", table_name="support_sessions")
    op.drop_table("support_sessions")
    op.drop_index("uq_support_operators_email_lookup_hash", table_name="support_operators")
    op.drop_table("support_operators")
