"""Bind order-backed license access to provider and separate activation/revocation.

Revision ID: 20261031_04
Revises: 20261031_03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20261031_04"
down_revision: Union[str, None] = "20261031_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP POLICY license_order_lookup ON licenses")
    op.execute("DROP POLICY license_order_update ON licenses")
    op.execute("DROP POLICY license_code_lookup ON licenses")

    op.execute(
        """CREATE POLICY license_code_lookup ON licenses FOR SELECT
        USING (
          NULLIF(current_setting('app.license_code_hash', true), '') IS NOT NULL
          AND code_hash = current_setting('app.license_code_hash', true)
          AND (
            NULLIF(current_setting('app.payment_provider', true), '') IS NULL
            OR EXISTS (
              SELECT 1 FROM orders o
              WHERE o.id = licenses.order_id
                AND o.provider = current_setting('app.payment_provider', true)
            )
          )
        )"""
    )
    op.execute(
        """CREATE POLICY license_order_lookup ON licenses FOR SELECT
        USING (
          order_id IS NOT NULL
          AND order_id = NULLIF(current_setting('app.payment_order_id', true), '')::uuid
          AND EXISTS (
            SELECT 1 FROM orders o
            WHERE o.id = licenses.order_id
              AND o.provider = NULLIF(current_setting('app.payment_provider', true), '')
          )
        )"""
    )
    op.execute(
        """CREATE POLICY license_order_update ON licenses FOR UPDATE
        USING (
          order_id IS NOT NULL
          AND order_id = NULLIF(current_setting('app.payment_order_id', true), '')::uuid
          AND EXISTS (
            SELECT 1 FROM orders o
            WHERE o.id = licenses.order_id
              AND o.provider = NULLIF(current_setting('app.payment_provider', true), '')
          )
        )
        WITH CHECK (
          order_id IS NOT NULL
          AND order_id = NULLIF(current_setting('app.payment_order_id', true), '')::uuid
          AND EXISTS (
            SELECT 1 FROM orders o
            WHERE o.id = licenses.order_id
              AND o.provider = NULLIF(current_setting('app.payment_provider', true), '')
          )
        )"""
    )

    op.execute(
        """CREATE FUNCTION guard_license_update() RETURNS trigger
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

          RAISE EXCEPTION 'license update is not a permitted activation or revocation'
            USING ERRCODE = '42501';
        END;
        $$"""
    )
    op.execute(
        "CREATE TRIGGER licenses_guard_update BEFORE UPDATE ON licenses "
        "FOR EACH ROW EXECUTE FUNCTION guard_license_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER licenses_guard_update ON licenses")
    op.execute("DROP FUNCTION guard_license_update()")
    op.execute("DROP POLICY license_order_lookup ON licenses")
    op.execute("DROP POLICY license_order_update ON licenses")
    op.execute("DROP POLICY license_code_lookup ON licenses")

    # Restores the weaker revision-03 policy set; downgrade is only for disposable databases.
    op.execute(
        """CREATE POLICY license_code_lookup ON licenses FOR SELECT
        USING (
          NULLIF(current_setting('app.license_code_hash', true), '') IS NOT NULL
          AND code_hash = current_setting('app.license_code_hash', true)
        )"""
    )
    op.execute(
        """CREATE POLICY license_order_lookup ON licenses FOR SELECT
        USING (
          order_id IS NOT NULL
          AND order_id = NULLIF(current_setting('app.payment_order_id', true), '')::uuid
        )"""
    )
    op.execute(
        """CREATE POLICY license_order_update ON licenses FOR UPDATE
        USING (
          order_id IS NOT NULL
          AND order_id = NULLIF(current_setting('app.payment_order_id', true), '')::uuid
        )
        WITH CHECK (
          order_id IS NOT NULL
          AND order_id = NULLIF(current_setting('app.payment_order_id', true), '')::uuid
        )"""
    )
