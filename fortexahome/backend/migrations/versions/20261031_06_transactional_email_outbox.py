"""Create encrypted transactional email outbox and restricted worker role.

Revision ID: 20261031_06
Revises: 20261031_05
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "20261031_06"
down_revision: Union[str, None] = "20261031_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _role_names() -> tuple[str, str]:
    settings = get_settings()
    for name in (settings.APP_DB_USER, settings.OUTBOX_DB_USER):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name):
            raise ValueError("Os papéis PostgreSQL devem usar identificadores simples")
    if settings.APP_DB_USER == settings.OUTBOX_DB_USER:
        raise ValueError("O papel operacional e o worker da outbox devem ser diferentes")
    if not settings.OUTBOX_DB_PASSWORD:
        raise ValueError("OUTBOX_DB_PASSWORD é necessária para criar o papel isolado do worker")
    return settings.APP_DB_USER, settings.OUTBOX_DB_USER


def upgrade() -> None:
    app_role, worker_role = _role_names()
    connection = op.get_bind()
    preparer = connection.dialect.identifier_preparer
    app_ident = preparer.quote(app_role)
    worker_ident = preparer.quote(worker_role)
    database_ident = preparer.quote(connection.scalar(sa.text("SELECT current_database()")))
    password_literal = connection.scalar(sa.select(sa.func.quote_literal(get_settings().OUTBOX_DB_PASSWORD)))

    role_exists = connection.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :name)"),
        {"name": worker_role},
    )
    if role_exists:
        op.execute(
            f"ALTER ROLE {worker_ident} WITH LOGIN PASSWORD {password_literal} "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
    else:
        op.execute(
            f"CREATE ROLE {worker_ident} WITH LOGIN PASSWORD {password_literal} "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
    worker_oid = connection.scalar(sa.text("SELECT oid FROM pg_roles WHERE rolname = :name"), {"name": worker_role})
    owned_relations = connection.execute(
        sa.text(
            "SELECT n.nspname, c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relowner = :role_oid AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
        ),
        {"role_oid": worker_oid},
    ).all()
    if owned_relations:
        raise RuntimeError("OUTBOX_DB_USER já é dono de objetos; use um papel worker dedicado e vazio")
    memberships = connection.execute(
        sa.text(
            "SELECT parent.rolname FROM pg_auth_members m "
            "JOIN pg_roles parent ON parent.oid = m.roleid "
            "WHERE m.member = :role_oid"
        ),
        {"role_oid": worker_oid},
    ).all()
    for (member_role,) in memberships:
        op.execute(f"REVOKE {preparer.quote(member_role)} FROM {worker_ident}")
    op.execute(f"GRANT CONNECT ON DATABASE {database_ident} TO {worker_ident}")

    op.create_table(
        "email_outbox",
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(64), nullable=True),
        sa.Column("provider_message_id", sa.String(128), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('activation_verification','password_reset','license_delivery')",
            name="ck_email_outbox_event_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','sent','dead','cancelled')",
            name="ck_email_outbox_status",
        ),
        sa.CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="ck_email_outbox_attempts"),
        sa.CheckConstraint(
            "(status = 'processing' AND claimed_by IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(status <> 'processing' AND claimed_by IS NULL AND lease_until IS NULL)",
            name="ck_email_outbox_lease",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_email_outbox_idempotency_key", "email_outbox", ["idempotency_key"], unique=True)
    op.create_index("ix_email_outbox_due", "email_outbox", ["status", "next_attempt_at", "created_at"])
    op.create_index("ix_email_outbox_aggregate", "email_outbox", ["aggregate_id", "event_type", "status"])

    op.execute("ALTER TABLE email_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE email_outbox FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY email_outbox_worker ON email_outbox TO {worker_ident} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY email_outbox_app_insert ON email_outbox FOR INSERT TO {app_ident} "
        "WITH CHECK (status = 'pending' AND attempt_count = 0 AND claimed_by IS NULL "
        "AND lease_until IS NULL AND payload_encrypted IS NOT NULL)"
    )
    op.execute(
        f"CREATE POLICY email_outbox_app_metadata ON email_outbox FOR SELECT TO {app_ident} "
        "USING (event_type = 'activation_verification' "
        "AND aggregate_id = NULLIF(current_setting('app.pending_activation_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY email_outbox_app_cancel ON email_outbox FOR UPDATE TO {app_ident} "
        "USING (event_type = 'activation_verification' "
        "AND aggregate_id = NULLIF(current_setting('app.pending_activation_id', true), '')::uuid "
        "AND status IN ('pending','processing')) "
        "WITH CHECK (event_type = 'activation_verification' "
        "AND aggregate_id = NULLIF(current_setting('app.pending_activation_id', true), '')::uuid "
        "AND status = 'cancelled')"
    )

    op.execute(f"REVOKE ALL ON email_outbox FROM PUBLIC, {app_ident}, {worker_ident}")
    op.execute(f"GRANT INSERT ON email_outbox TO {app_ident}")
    op.execute(f"GRANT SELECT (event_type, aggregate_id, status) ON email_outbox TO {app_ident}")
    op.execute(
        f"GRANT UPDATE (status, processed_at, payload_encrypted, claimed_by, lease_until, last_error) "
        f"ON email_outbox TO {app_ident}"
    )
    op.execute(f"GRANT SELECT ON email_outbox TO {worker_ident}")
    op.execute(f"GRANT UPDATE ON email_outbox TO {worker_ident}")

    # Existing or bootstrap-created worker roles must not retain unrelated grants.
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {worker_ident}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {worker_ident}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {worker_ident}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {worker_ident}")
    op.execute(f"GRANT SELECT, UPDATE ON email_outbox TO {worker_ident}")


def downgrade() -> None:
    _, worker_role = _role_names()
    worker_ident = op.get_bind().dialect.identifier_preparer.quote(worker_role)
    op.execute(f"DROP POLICY IF EXISTS email_outbox_app_cancel ON email_outbox")
    op.execute(f"DROP POLICY IF EXISTS email_outbox_app_metadata ON email_outbox")
    op.execute(f"DROP POLICY IF EXISTS email_outbox_app_insert ON email_outbox")
    op.execute(f"DROP POLICY IF EXISTS email_outbox_worker ON email_outbox")
    op.drop_index("ix_email_outbox_aggregate", table_name="email_outbox")
    op.drop_index("ix_email_outbox_due", table_name="email_outbox")
    op.drop_index("uq_email_outbox_idempotency_key", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.execute(f"DROP OWNED BY {worker_ident}")
    op.execute(f"DROP ROLE {worker_ident}")
