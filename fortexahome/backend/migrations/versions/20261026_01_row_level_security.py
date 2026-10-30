"""row level security for tenant-owned tables

Revision ID: 20261026_01
Revises: 097fe0849068
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261026_01"
down_revision: Union[str, None] = "097fe0849068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "categories",
    "transactions",
    "bills",
    "credit_cards",
    "budgets",
    "goals",
    "goal_movements",
    "subscriptions",
]

TENANT_POLICY = """
CREATE POLICY tenant_isolation ON {table}
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
"""


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(TENANT_POLICY.format(table=table))

    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenants
          USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
          WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )

    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON users
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY login_lookup ON users FOR SELECT
          USING (
            NULLIF(current_setting('app.login_email_hash', true), '') IS NOT NULL
            AND email_lookup_hash = current_setting('app.login_email_hash', true)
          );
        """
    )

    op.execute("ALTER TABLE sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sessions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON sessions
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY session_lookup ON sessions FOR SELECT
          USING (
            NULLIF(current_setting('app.session_token_hash', true), '') IS NOT NULL
            AND token_hash = current_setting('app.session_token_hash', true)
          );
        """
    )

    op.execute("ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_reset_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON password_reset_tokens
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY reset_lookup ON password_reset_tokens FOR SELECT
          USING (
            NULLIF(current_setting('app.password_reset_hash', true), '') IS NOT NULL
            AND token_hash = current_setting('app.password_reset_hash', true)
          );
        """
    )

    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_tenant_select ON audit_logs FOR SELECT
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute("CREATE POLICY audit_insert ON audit_logs FOR INSERT WITH CHECK (true);")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_insert ON audit_logs")
    op.execute("DROP POLICY IF EXISTS audit_tenant_select ON audit_logs")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS reset_lookup ON password_reset_tokens")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON password_reset_tokens")
    op.execute("ALTER TABLE password_reset_tokens DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS session_lookup ON sessions")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sessions")
    op.execute("ALTER TABLE sessions DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS login_lookup ON users")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
