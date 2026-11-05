"""Allow temporary license recovery and scoped delivery cancellation.

Revision ID: 20261031_11
Revises: 20261031_10
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op

from app.core.config import get_settings


revision: str = "20261031_11"
down_revision: Union[str, None] = "20261031_10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GUARD_FUNCTION_HEAD = """
CREATE OR REPLACE FUNCTION guard_license_update() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
  context_tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
  context_code text := NULLIF(current_setting('app.license_code_hash', true), '');
  context_provider text := NULLIF(current_setting('app.payment_provider', true), '');
  context_order uuid := NULLIF(current_setting('app.payment_order_id', true), '')::uuid;
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
"""

_GUARD_FUNCTION_RECOVERY = """
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
"""

_GUARD_FUNCTION_REVOCATION = """
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

_OLD_GUARD_FUNCTION = _GUARD_FUNCTION_HEAD + _GUARD_FUNCTION_REVOCATION.replace(
    "license update is not a permitted activation, recovery or revocation",
    "license update is not a permitted activation or revocation",
)
_NEW_GUARD_FUNCTION = _GUARD_FUNCTION_HEAD + _GUARD_FUNCTION_RECOVERY + _GUARD_FUNCTION_REVOCATION


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

    op.execute(
        f"CREATE POLICY license_delivery_worker_status ON licenses FOR SELECT TO {worker_ident} "
        "USING (id = NULLIF(current_setting('app.outbox_license_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY order_delivery_worker_status ON orders FOR SELECT TO {worker_ident} "
        "USING (id = NULLIF(current_setting('app.outbox_order_id', true), '')::uuid)"
    )
    op.execute(f"GRANT SELECT (id, status, order_id) ON licenses TO {worker_ident}")
    op.execute(f"GRANT SELECT (id, provider, status) ON orders TO {worker_ident}")

    op.execute(
        f"CREATE POLICY email_outbox_app_license_metadata ON email_outbox FOR SELECT TO {app_ident} "
        "USING (event_type = 'license_delivery' "
        "AND aggregate_id = NULLIF(current_setting('app.outbox_license_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY email_outbox_app_license_cancel ON email_outbox FOR UPDATE TO {app_ident} "
        "USING (event_type = 'license_delivery' "
        "AND aggregate_id = NULLIF(current_setting('app.outbox_license_id', true), '')::uuid "
        "AND status IN ('pending','processing')) "
        "WITH CHECK (event_type = 'license_delivery' "
        "AND aggregate_id = NULLIF(current_setting('app.outbox_license_id', true), '')::uuid "
        "AND status = 'cancelled')"
    )

    op.execute(_NEW_GUARD_FUNCTION)


def downgrade() -> None:
    _, worker_role = _roles()
    preparer = op.get_bind().dialect.identifier_preparer
    worker_ident = preparer.quote(worker_role)

    op.execute("DROP POLICY IF EXISTS email_outbox_app_license_cancel ON email_outbox")
    op.execute("DROP POLICY IF EXISTS email_outbox_app_license_metadata ON email_outbox")
    op.execute("DROP POLICY IF EXISTS order_delivery_worker_status ON orders")
    op.execute("DROP POLICY IF EXISTS license_delivery_worker_status ON licenses")
    op.execute(f"REVOKE SELECT (id, provider, status) ON orders FROM {worker_ident}")
    op.execute(f"REVOKE SELECT (id, status, order_id) ON licenses FROM {worker_ident}")

    # Restore the guard from 20261031_04; no commercial history is removed.
    op.execute(_OLD_GUARD_FUNCTION)
