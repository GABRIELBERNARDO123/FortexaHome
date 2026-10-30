"""row level security for licenses

Revision ID: 20261026_02
Revises: 20261026_01
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261026_02"
down_revision: Union[str, None] = "20261026_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE licenses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE licenses FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY license_tenant ON licenses
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY license_code_lookup ON licenses FOR SELECT
          USING (
            NULLIF(current_setting('app.license_code_hash', true), '') IS NOT NULL
            AND code_hash = current_setting('app.license_code_hash', true)
          );
        """
    )
    op.execute(
        "CREATE POLICY license_pending_insert ON licenses FOR INSERT WITH CHECK (tenant_id IS NULL);"
    )
    op.execute(
        """
        CREATE POLICY license_activation_update ON licenses FOR UPDATE
          USING (
            tenant_id IS NULL
            AND NULLIF(current_setting('app.license_code_hash', true), '') IS NOT NULL
            AND code_hash = current_setting('app.license_code_hash', true)
          )
          WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS license_activation_update ON licenses")
    op.execute("DROP POLICY IF EXISTS license_pending_insert ON licenses")
    op.execute("DROP POLICY IF EXISTS license_code_lookup ON licenses")
    op.execute("DROP POLICY IF EXISTS license_tenant ON licenses")
    op.execute("ALTER TABLE licenses DISABLE ROW LEVEL SECURITY")
