"""Restrict commerce tables to product reads and provider-scoped webhook flows.

Revision ID: 20261031_03
Revises: 20261026_02
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op

from app.core.config import get_settings

revision: str = "20261031_03"
down_revision: Union[str, None] = "20261026_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("products", "orders", "payment_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute("CREATE POLICY products_read ON products FOR SELECT USING (true)")
    op.execute(
        """CREATE POLICY products_catalog_write ON products FOR ALL
        USING (current_setting('app.catalog_write', true) = 'true')
        WITH CHECK (current_setting('app.catalog_write', true) = 'true')"""
    )
    op.execute(
        """CREATE POLICY orders_provider_scope ON orders
        USING (provider = NULLIF(current_setting('app.payment_provider', true), ''))
        WITH CHECK (provider = NULLIF(current_setting('app.payment_provider', true), ''))"""
    )
    op.execute(
        """CREATE POLICY payment_events_provider_scope ON payment_events
        USING (provider = NULLIF(current_setting('app.payment_provider', true), ''))
        WITH CHECK (provider = NULLIF(current_setting('app.payment_provider', true), ''))"""
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

    role = get_settings().APP_DB_USER
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", role):
        raise ValueError("APP_DB_USER deve ser um identificador PostgreSQL simples")
    op.execute(f"REVOKE ALL ON products, orders, payment_events FROM {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON products TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON orders TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON payment_events TO {role}")
    op.execute(f"REVOKE ALL ON licenses FROM {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON licenses TO {role}")


def downgrade() -> None:
    role = get_settings().APP_DB_USER
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", role):
        raise ValueError("APP_DB_USER deve ser um identificador PostgreSQL simples")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON products, orders, payment_events TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON licenses TO {role}")
    op.execute("DROP POLICY IF EXISTS license_order_lookup ON licenses")
    op.execute("DROP POLICY IF EXISTS license_order_update ON licenses")
    op.execute("DROP POLICY IF EXISTS payment_events_provider_scope ON payment_events")
    op.execute("DROP POLICY IF EXISTS orders_provider_scope ON orders")
    op.execute("DROP POLICY IF EXISTS products_read ON products")
    op.execute("DROP POLICY IF EXISTS products_catalog_write ON products")
    for table in ("products", "orders", "payment_events"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
