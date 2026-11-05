"""Add LGPD data subject requests, audit events and deletion tombstones.

Revision ID: 20261104_18
Revises: 20261104_17
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings


revision: str = "20261104_18"
down_revision: Union[str, None] = "20261104_17"
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


_PRIVACY_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION guard_license_update() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
  context_tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
  context_code text := NULLIF(current_setting('app.license_code_hash', true), '');
  context_provider text := NULLIF(current_setting('app.payment_provider', true), '');
  context_order uuid := NULLIF(current_setting('app.payment_order_id', true), '')::uuid;
  context_privacy text := NULLIF(current_setting('app.privacy_erasure', true), '');
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.product_id IS DISTINCT FROM OLD.product_id
     OR NEW.order_id IS DISTINCT FROM OLD.order_id
     OR NEW.code_hash IS DISTINCT FROM OLD.code_hash
     OR NEW.code_last4 IS DISTINCT FROM OLD.code_last4
     OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
     OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
    RAISE EXCEPTION 'commercial license fields are immutable' USING ERRCODE = '42501';
  END IF;

  IF OLD.tenant_id IS NULL
     AND OLD.status IN ('pending', 'active')
     AND context_code = OLD.code_hash
     AND context_tenant IS NOT NULL
     AND NEW.tenant_id = context_tenant
     AND NEW.status = 'active'
     AND NEW.activated_at IS NOT NULL
     AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at THEN
    RETURN NEW;
  END IF;

  IF OLD.status = 'suspended'
     AND NEW.status IN ('pending', 'active')
     AND NEW.tenant_id IS NOT DISTINCT FROM OLD.tenant_id
     AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
     AND NEW.bound_email_hash IS NOT DISTINCT FROM OLD.bound_email_hash
     AND NEW.revoked_at IS NULL
     AND OLD.order_id IS NOT NULL
     AND (OLD.tenant_id IS NULL OR NEW.status = 'active')
     AND context_provider IS NOT NULL
     AND context_order = OLD.order_id
     AND EXISTS (
       SELECT 1 FROM public.orders o
       WHERE o.id = OLD.order_id
         AND o.provider = context_provider
         AND o.status = 'paid'
     ) THEN
    RETURN NEW;
  END IF;

  IF context_privacy = 'true'
     AND NEW.status = 'cancelled'
     AND NEW.revoked_at IS NOT NULL
     AND NEW.tenant_id IS NULL
     AND NEW.bound_email_hash IS NULL
     AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
     AND NEW.order_id IS NOT DISTINCT FROM OLD.order_id THEN
    RETURN NEW;
  END IF;

  IF NEW.tenant_id IS NOT DISTINCT FROM OLD.tenant_id
     AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
     AND NEW.bound_email_hash IS NOT DISTINCT FROM OLD.bound_email_hash
     AND NEW.status IN ('cancelled', 'suspended')
     AND NEW.revoked_at IS NOT NULL
     AND OLD.order_id IS NOT NULL
     AND context_provider IS NOT NULL
     AND context_order = OLD.order_id
     AND EXISTS (
       SELECT 1 FROM public.orders o
       WHERE o.id = OLD.order_id AND o.provider = context_provider
     ) THEN
    RETURN NEW;
  END IF;

  RAISE EXCEPTION 'license update is not a permitted activation, recovery or revocation'
    USING ERRCODE = '42501';
END;
$$;
"""

_PRIVACY_BRANCH = """  IF context_privacy = 'true'
     AND NEW.status = 'cancelled'
     AND NEW.revoked_at IS NOT NULL
     AND NEW.tenant_id IS NULL
     AND NEW.bound_email_hash IS NULL
     AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
     AND NEW.order_id IS NOT DISTINCT FROM OLD.order_id THEN
    RETURN NEW;
  END IF;

"""


def upgrade() -> None:
    app_role, worker_role = _roles()
    preparer = op.get_bind().dialect.identifier_preparer
    app_ident = preparer.quote(app_role)
    worker_ident = preparer.quote(worker_role)

    op.create_table(
        "privacy_requests",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("request_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="submitted", nullable=False),
        sa.Column("scope", sa.String(16), server_default="user", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("verification_method", sa.String(32), server_default="password", nullable=False),
        sa.Column("retention_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("review_justification", sa.Text(), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "request_type IN ('erasure','access','correction','anonymization','blocking','portability','information')",
            name="ck_privacy_requests_type",
        ),
        sa.CheckConstraint(
            "status IN ('submitted','awaiting_review','approved','processing','completed',"
            "'partially_completed','rejected','cancelled')",
            name="ck_privacy_requests_status",
        ),
        sa.CheckConstraint("scope IN ('user','tenant')", name="ck_privacy_requests_scope"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["support_operators.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_privacy_requests_protocol", "privacy_requests", ["protocol"], unique=True)
    op.create_index("ix_privacy_requests_tenant_created", "privacy_requests", ["tenant_id", "created_at"])
    op.create_index("ix_privacy_requests_user_created", "privacy_requests", ["user_id", "created_at"])
    op.create_index(
        "uq_privacy_requests_active_erasure",
        "privacy_requests",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text(
            "request_type = 'erasure' AND status IN ('submitted','awaiting_review','approved','processing')"
        ),
    )

    op.create_table(
        "privacy_request_events",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["privacy_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_request_events_request", "privacy_request_events", ["request_id", "created_at"])
    op.create_index("ix_privacy_request_events_tenant", "privacy_request_events", ["tenant_id", "created_at"])

    op.create_table(
        "data_deletion_tombstones",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("scope IN ('user','tenant')", name="ck_data_deletion_tombstones_scope"),
        sa.ForeignKeyConstraint(["request_id"], ["privacy_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_deletion_tombstones_tenant", "data_deletion_tombstones", ["tenant_id", "created_at"])
    op.create_index("ix_data_deletion_tombstones_user", "data_deletion_tombstones", ["user_id"])

    for table in ("privacy_requests", "privacy_request_events", "data_deletion_tombstones"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC, {app_ident}, {worker_ident}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {app_ident}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} TO {app_ident} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    op.execute(
        f"CREATE POLICY privacy_support_read ON privacy_requests FOR SELECT TO {app_ident} "
        "USING (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
    )
    op.execute(
        f"CREATE POLICY privacy_support_update ON privacy_requests FOR UPDATE TO {app_ident} "
        "USING (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL) "
        "WITH CHECK (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
    )
    op.execute(
        f"CREATE POLICY privacy_event_support_read ON privacy_request_events FOR SELECT TO {app_ident} "
        "USING (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
    )
    op.execute(
        f"CREATE POLICY privacy_event_support_insert ON privacy_request_events FOR INSERT TO {app_ident} "
        "WITH CHECK (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
    )
    op.execute(
        f"CREATE POLICY tombstone_support_read ON data_deletion_tombstones FOR SELECT TO {app_ident} "
        "USING (NULLIF(current_setting('app.support_operator_id', true), '') IS NOT NULL)"
    )
    op.execute(
        f"CREATE POLICY email_outbox_privacy_select ON email_outbox FOR SELECT TO {app_ident} "
        "USING (current_setting('app.privacy_erasure', true) = 'true')"
    )
    op.execute(
        f"CREATE POLICY email_outbox_privacy_update ON email_outbox FOR UPDATE TO {app_ident} "
        "USING (current_setting('app.privacy_erasure', true) = 'true') "
        "WITH CHECK (current_setting('app.privacy_erasure', true) = 'true')"
    )
    op.execute(
        f"CREATE POLICY license_privacy_select ON licenses FOR SELECT TO {app_ident} "
        "USING (current_setting('app.privacy_erasure', true) = 'true')"
    )
    op.execute(
        f"CREATE POLICY order_privacy_select ON orders FOR SELECT TO {app_ident} "
        "USING (current_setting('app.privacy_erasure', true) = 'true')"
    )
    op.execute(
        f"CREATE POLICY order_privacy_update ON orders FOR UPDATE TO {app_ident} "
        "USING (current_setting('app.privacy_erasure', true) = 'true') "
        "WITH CHECK (current_setting('app.privacy_erasure', true) = 'true')"
    )
    op.execute(
        f"CREATE POLICY license_privacy_erasure ON licenses FOR UPDATE TO {app_ident} "
        "USING (current_setting('app.privacy_erasure', true) = 'true') "
        "WITH CHECK (current_setting('app.privacy_erasure', true) = 'true')"
    )
    op.execute(_PRIVACY_GUARD_FUNCTION)


def downgrade() -> None:
    app_role, _ = _roles()
    preparer = op.get_bind().dialect.identifier_preparer
    app_ident = preparer.quote(app_role)

    op.execute(_PRIVACY_GUARD_FUNCTION.replace(_PRIVACY_BRANCH, ""))
    op.execute("DROP POLICY IF EXISTS order_privacy_update ON orders")
    op.execute("DROP POLICY IF EXISTS order_privacy_select ON orders")
    op.execute("DROP POLICY IF EXISTS license_privacy_select ON licenses")
    op.execute("DROP POLICY IF EXISTS license_privacy_erasure ON licenses")
    op.execute("DROP POLICY IF EXISTS email_outbox_privacy_update ON email_outbox")
    op.execute("DROP POLICY IF EXISTS email_outbox_privacy_select ON email_outbox")
    op.execute("DROP POLICY IF EXISTS tombstone_support_read ON data_deletion_tombstones")
    op.execute("DROP POLICY IF EXISTS privacy_event_support_insert ON privacy_request_events")
    op.execute("DROP POLICY IF EXISTS privacy_event_support_read ON privacy_request_events")
    op.execute("DROP POLICY IF EXISTS privacy_support_update ON privacy_requests")
    op.execute("DROP POLICY IF EXISTS privacy_support_read ON privacy_requests")
    for table in ("data_deletion_tombstones", "privacy_request_events", "privacy_requests"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {app_ident}")

    op.drop_index("ix_data_deletion_tombstones_user", table_name="data_deletion_tombstones")
    op.drop_index("ix_data_deletion_tombstones_tenant", table_name="data_deletion_tombstones")
    op.drop_table("data_deletion_tombstones")
    op.drop_index("ix_privacy_request_events_tenant", table_name="privacy_request_events")
    op.drop_index("ix_privacy_request_events_request", table_name="privacy_request_events")
    op.drop_table("privacy_request_events")
    op.drop_index("uq_privacy_requests_active_erasure", table_name="privacy_requests")
    op.drop_index("ix_privacy_requests_user_created", table_name="privacy_requests")
    op.drop_index("ix_privacy_requests_tenant_created", table_name="privacy_requests")
    op.drop_index("uq_privacy_requests_protocol", table_name="privacy_requests")
    op.drop_table("privacy_requests")
