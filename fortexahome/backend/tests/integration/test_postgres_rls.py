from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.database import engine, set_db_context
from app.core.field_encryption import license_code_hash
from app.models.category import Category
from app.models.license import License
from app.models.order import Order
from app.models.payment_event import PaymentEvent
from app.models.product import Product
from app.models.tenant import Tenant
from app.services.license_service import get_license_by_code, issue_license
from app import main

pytestmark = pytest.mark.integration


@pytest.fixture
def db(integration_database):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_runtime_role_and_protected_tables_enforce_rls(db):
    flags = db.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    assert flags == (False, False)
    rows = db.execute(
        text(
            """SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class WHERE relname = ANY(:tables)"""
        ),
        {
            "tables": [
                "tenants", "users", "categories", "transactions", "bills", "credit_cards",
                "budgets", "goals", "goal_movements", "subscriptions", "sessions",
                "password_reset_tokens", "audit_logs", "licenses", "products", "orders", "payment_events",
                "pending_activations", "email_outbox",
            ]
        },
    ).all()
    assert len(rows) == 19
    assert all(enabled and forced for _, enabled, forced in rows)


def test_tenant_rows_are_isolated_between_two_tenants(db):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    set_db_context(db, tenant_id=tenant_a)
    db.add(Tenant(id=tenant_a, name="Tenant A"))
    db.flush()
    db.add(Category(tenant_id=tenant_a, name="A only", kind="expense"))
    db.flush()

    set_db_context(db, tenant_id=tenant_b)
    db.add(Tenant(id=tenant_b, name="Tenant B"))
    db.flush()
    db.add(Category(tenant_id=tenant_b, name="B only", kind="expense"))
    db.flush()
    assert [item.name for item in db.scalars(select(Category)).all()] == ["B only"]
    assert db.scalar(select(Tenant.name)) == "Tenant B"


def test_license_code_lookup_and_order_lookup_work_under_rls(db):
    code = "FH-TEST-RLS-0001"
    product = Product(
        slug=f"test-{uuid.uuid4().hex[:10]}", name="Integration", price_cents=100,
        currency="BRL", license_kind="lifetime", active=True,
    )
    set_db_context(db, catalog_write="true")
    db.add(product)
    db.flush()
    provider = "test_provider"
    set_db_context(db, payment_provider=provider)
    order = Order(
        provider=provider, external_order_id=f"order-{uuid.uuid4()}", product_id=product.id,
        amount_cents=100, currency="BRL", status="paid",
    )
    db.add(order)
    db.flush()
    license_row, _ = issue_license(db, product, order_id=order.id, code=code)
    assert get_license_by_code(db, code).id == license_row.id
    set_db_context(db, payment_order_id=order.id)
    assert db.scalar(select(License).where(License.order_id == order.id)).id == license_row.id
    license_row.status = "cancelled"
    license_row.revoked_at = datetime.now(timezone.utc)
    db.flush()
    assert db.scalar(select(License).where(License.order_id == order.id)).status == "cancelled"
    assert db.scalar(select(Order).where(Order.id == order.id)).id == order.id


def _clear_payment_context(db):
    context = db.info.setdefault("rls_context", {})
    for key in ("payment_provider", "payment_order_id", "license_code_hash"):
        context[key] = None
    db.execute(
        text(
            "SELECT set_config('app.payment_provider', '', true), "
            "set_config('app.payment_order_id', '', true), "
            "set_config('app.license_code_hash', '', true)"
        )
    )


def test_provider_isolation_for_orders_events_and_order_licenses(db):
    product = Product(
        slug=f"providers-{uuid.uuid4().hex[:10]}", name="Provider scope", price_cents=1,
        currency="BRL", license_kind="lifetime", active=True,
    )
    set_db_context(db, catalog_write="true")
    db.add(product)
    db.flush()

    provider_orders = {}
    provider_events = {}
    for provider in ("provider_a", "provider_b"):
        set_db_context(db, payment_provider=provider)
        order = Order(
            provider=provider, external_order_id=str(uuid.uuid4()), product_id=product.id,
            amount_cents=1, currency="BRL", status="paid",
        )
        db.add(order)
        db.flush()
        event = PaymentEvent(
            provider=provider, external_event_id=str(uuid.uuid4()), event_type="payment.paid",
            order_id=order.id, payload_hash="a" * 64,
        )
        db.add(event)
        db.flush()
        provider_orders[provider] = order
        provider_events[provider] = event

    set_db_context(db, payment_provider="provider_b")
    license_row, code = issue_license(
        db, product, order_id=provider_orders["provider_b"].id, code="FH-PROVIDER-B-0001"
    )
    _clear_payment_context(db)

    order_b = provider_orders["provider_b"]
    event_b = provider_events["provider_b"]
    set_db_context(db, payment_provider="provider_a", payment_order_id=order_b.id)
    assert db.scalar(select(Order).where(Order.id == order_b.id)) is None
    assert db.scalar(select(PaymentEvent).where(PaymentEvent.id == event_b.id)) is None
    assert db.scalar(select(License).where(License.id == license_row.id)) is None
    blocked = db.execute(
        update(License).where(License.id == license_row.id).values(
            status="cancelled", revoked_at=datetime.now(timezone.utc)
        )
    )
    assert blocked.rowcount == 0

    set_db_context(db, payment_provider="provider_b", payment_order_id=uuid.uuid4())
    assert db.scalar(select(License).where(License.id == license_row.id)) is None
    blocked = db.execute(
        update(License).where(License.id == license_row.id).values(
            status="cancelled", revoked_at=datetime.now(timezone.utc)
        )
    )
    assert blocked.rowcount == 0

    set_db_context(db, payment_provider="provider_a", payment_order_id=order_b.id)
    assert get_license_by_code(db, code) is None
    blocked = db.execute(
        update(License).where(License.id == license_row.id).values(
            status="suspended", revoked_at=datetime.now(timezone.utc)
        )
    )
    assert blocked.rowcount == 0

    set_db_context(db, payment_provider="provider_b", payment_order_id=order_b.id)
    assert db.scalar(select(Order).where(Order.id == order_b.id)).id == order_b.id
    assert db.scalar(select(PaymentEvent).where(PaymentEvent.id == event_b.id)).id == event_b.id
    assert db.scalar(select(License).where(License.id == license_row.id)).id == license_row.id
    license_row.status = "cancelled"
    license_row.revoked_at = datetime.now(timezone.utc)
    db.flush()
    assert db.scalar(select(License).where(License.id == license_row.id)).status == "cancelled"


def test_commerce_permissions_are_limited(db):
    privileges = db.execute(
        text(
            """SELECT table_name, privilege_type FROM information_schema.role_table_grants
            WHERE grantee = current_user AND table_name = ANY(:tables)"""
        ),
        {"tables": ["products", "orders", "payment_events", "licenses", "pending_activations"]},
    ).all()
    grant_map = {}
    for table, privilege in privileges:
        grant_map.setdefault(table, set()).add(privilege)
    assert grant_map["products"] == {"SELECT", "INSERT", "UPDATE"}
    assert grant_map["orders"] == {"SELECT", "INSERT", "UPDATE"}
    assert grant_map["payment_events"] == {"SELECT", "INSERT"}
    assert grant_map["licenses"] == {"SELECT", "INSERT", "UPDATE"}
    assert grant_map["pending_activations"] == {"SELECT", "INSERT", "UPDATE"}


def test_catalog_and_order_writes_require_explicit_context(db):
    product = Product(
        slug=f"blocked-{uuid.uuid4().hex[:10]}", name="Blocked", price_cents=1,
        currency="BRL", license_kind="lifetime", active=True,
    )
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.add(product)
            db.flush()

    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.add(
                Order(
                    provider="missing_context", external_order_id=str(uuid.uuid4()),
                    product_id=uuid.uuid4(), amount_cents=1, currency="BRL", status="pending",
                )
            )
            db.flush()


def test_license_activation_update_requires_code_and_tenant_context(db):
    product = Product(
        slug=f"activate-{uuid.uuid4().hex[:10]}", name="Activate", price_cents=1,
        currency="BRL", license_kind="lifetime", active=True,
    )
    set_db_context(db, catalog_write="true")
    db.add(product)
    db.flush()
    code = "FH-TEST-ACTIVATE-002"
    provider = "activation_provider"
    set_db_context(db, payment_provider=provider)
    order = Order(
        provider=provider, external_order_id=str(uuid.uuid4()), product_id=product.id,
        amount_cents=1, currency="BRL", status="paid",
    )
    db.add(order)
    db.flush()
    license_row, _ = issue_license(db, product, order_id=order.id, code=code)
    tenant_id = uuid.uuid4()
    set_db_context(db, tenant_id=tenant_id)
    db.add(Tenant(id=tenant_id, name="Activated"))
    db.flush()
    set_db_context(db, license_code_hash=license_code_hash(code))
    from app.services.license_service import bind_license

    bind_license(db, license_row, tenant_id, "buyer-hash")
    activated_at = license_row.activated_at
    assert license_row.tenant_id == tenant_id
    assert license_row.bound_email_hash == "buyer-hash"

    set_db_context(db, payment_provider=provider, payment_order_id=order.id)
    license_row.status = "suspended"
    license_row.revoked_at = datetime.now(timezone.utc)
    db.flush()
    assert license_row.tenant_id == tenant_id
    assert license_row.activated_at == activated_at
    assert license_row.bound_email_hash == "buyer-hash"

    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(
                update(License).where(License.id == license_row.id).values(
                    tenant_id=uuid.uuid4(), bound_email_hash="reassigned",
                    status="cancelled", revoked_at=datetime.now(timezone.utc),
                )
            )
    assert license_row.tenant_id == tenant_id
    assert license_row.bound_email_hash == "buyer-hash"


def test_database_health_check_and_startup(integration_database):
    with TestClient(main.app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["database"] == "up"


def test_z_corrective_migration_downgrade_and_reupgrade(integration_database):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    command.downgrade(config, "20261031_03")
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        trigger_exists = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'licenses_guard_update')")
        )
        old_policy = connection.scalar(
            text("SELECT qual FROM pg_policies WHERE tablename = 'licenses' AND policyname = 'license_order_lookup'")
        )
    assert revision == "20261031_03"
    assert not trigger_exists
    assert "payment_order_id" in old_policy
    assert "payment_provider" not in old_policy

    command.upgrade(config, "head")
    with engine.connect() as connection:
        trigger_exists = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'licenses_guard_update')")
        )
        new_policy = connection.scalar(
            text("SELECT qual FROM pg_policies WHERE tablename = 'licenses' AND policyname = 'license_order_lookup'")
        )
        delivery_policies = connection.scalar(
            text(
                "SELECT count(*) FROM pg_policies WHERE policyname IN "
                "('license_delivery_worker_status', 'order_delivery_worker_status', "
                "'email_outbox_app_license_cancel', 'email_outbox_app_license_metadata')"
            )
        )
        license_columns_ok = connection.scalar(
            text(
                "SELECT bool_and(has_column_privilege(:worker, 'licenses', column_name, 'SELECT')) "
                "FROM unnest(ARRAY['id','status','order_id']) AS column_name"
            ),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
        order_columns_ok = connection.scalar(
            text(
                "SELECT bool_and(has_column_privilege(:worker, 'orders', column_name, 'SELECT')) "
                "FROM unnest(ARRAY['id','provider','status']) AS column_name"
            ),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
        guard_definition = connection.scalar(
            text("SELECT pg_get_functiondef('guard_license_update()'::regprocedure)")
        )
    assert trigger_exists
    assert "payment_provider" in new_policy
    assert delivery_policies == 4
    assert license_columns_ok is True
    assert order_columns_ok is True
    assert "OLD.status = 'suspended'" in guard_definition


def test_zz_delivery_lifecycle_migration_downgrade_and_reupgrade(integration_database):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    command.downgrade(config, "20261031_10")
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        delivery_policies = connection.scalar(
            text(
                "SELECT count(*) FROM pg_policies WHERE policyname IN "
                "('license_delivery_worker_status', 'order_delivery_worker_status', "
                "'email_outbox_app_license_cancel', 'email_outbox_app_license_metadata')"
            )
        )
        worker_has_license_status = connection.scalar(
            text("SELECT has_column_privilege(:worker, 'licenses', 'status', 'SELECT')"),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
        guard_definition = connection.scalar(
            text("SELECT pg_get_functiondef('guard_license_update()'::regprocedure)")
        )
        support_tables = connection.scalar(
            text("SELECT to_regclass('public.support_operators')")
        )
        rate_limit_table = connection.scalar(
            text("SELECT to_regclass('public.rate_limit_buckets')")
        )
        reconciliation_table = connection.scalar(
            text("SELECT to_regclass('public.hotmart_reconciliation_observations')")
        )
        lockout_table = connection.scalar(
            text("SELECT to_regclass('public.login_lockout_states')")
        )
    assert revision == "20261031_10"
    assert delivery_policies == 0
    assert not worker_has_license_status
    assert "OLD.status = 'suspended'" not in guard_definition
    assert support_tables is None
    assert rate_limit_table is None
    assert reconciliation_table is None
    assert lockout_table is None

    command.upgrade(config, "head")
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        delivery_policies = connection.scalar(
            text(
                "SELECT count(*) FROM pg_policies WHERE policyname IN "
                "('license_delivery_worker_status', 'order_delivery_worker_status', "
                "'email_outbox_app_license_cancel', 'email_outbox_app_license_metadata')"
            )
        )
        guard_definition = connection.scalar(
            text("SELECT pg_get_functiondef('guard_license_update()'::regprocedure)")
        )
        support_tables = connection.scalar(
            text("SELECT to_regclass('public.support_operators')")
        )
        support_policies = connection.scalar(
            text("SELECT count(*) FROM pg_policies WHERE tablename = 'support_operators'")
        )
        category_archived = connection.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'categories' AND column_name = 'archived'"
            )
        )
        rate_limit_table = connection.scalar(
            text("SELECT to_regclass('public.rate_limit_buckets')")
        )
        app_rate_privileges = connection.scalar(
            text(
                "SELECT bool_and(has_table_privilege(:app, 'rate_limit_buckets', privilege)) "
                "FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS privilege"
            ),
            {"app": os.environ["APP_DB_USER"]},
        )
        worker_rate_privilege = connection.scalar(
            text("SELECT has_table_privilege(:worker, 'rate_limit_buckets', 'SELECT')"),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
        reconciliation_table = connection.scalar(
            text("SELECT to_regclass('public.hotmart_reconciliation_observations')")
        )
        app_reconciliation_users = connection.scalar(
            text(
                "SELECT has_table_privilege(:app, 'hotmart_reconciliation_observations', 'SELECT') "
                "AND has_table_privilege(:app, 'hotmart_reconciliation_observations', 'INSERT')"
            ),
            {"app": os.environ["APP_DB_USER"]},
        )
        app_reconciliation_mutate = connection.scalar(
            text(
                "SELECT has_table_privilege(:app, 'hotmart_reconciliation_observations', 'UPDATE') "
                "OR has_table_privilege(:app, 'hotmart_reconciliation_observations', 'DELETE')"
            ),
            {"app": os.environ["APP_DB_USER"]},
        )
        worker_reconciliation_access = connection.scalar(
            text("SELECT has_table_privilege(:worker, 'hotmart_reconciliation_observations', 'SELECT')"),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
        lockout_table = connection.scalar(
            text("SELECT to_regclass('public.login_lockout_states')")
        )
        app_lockout_privileges = connection.scalar(
            text(
                "SELECT bool_and(has_table_privilege(:app, 'login_lockout_states', privilege)) "
                "FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS privilege"
            ),
            {"app": os.environ["APP_DB_USER"]},
        )
        worker_lockout_access = connection.scalar(
            text("SELECT has_table_privilege(:worker, 'login_lockout_states', 'SELECT')"),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
        idempotency_table = connection.scalar(
            text("SELECT to_regclass('public.idempotency_records')")
        )
        app_idempotency_privileges = connection.scalar(
            text(
                "SELECT bool_and(has_table_privilege(:app, 'idempotency_records', privilege)) "
                "FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS privilege"
            ),
            {"app": os.environ["APP_DB_USER"]},
        )
        worker_idempotency_access = connection.scalar(
            text("SELECT has_table_privilege(:worker, 'idempotency_records', 'SELECT')"),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
        idempotency_rls = connection.scalar(
            text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE relname = 'idempotency_records'"
            )
        )
        privacy_tables = connection.scalar(
            text(
                "SELECT count(*) FROM pg_class WHERE relname IN "
                "('privacy_requests','privacy_request_events','data_deletion_tombstones') "
                "AND relrowsecurity AND relforcerowsecurity"
            )
        )
        privacy_policies = connection.scalar(
            text(
                "SELECT count(*) FROM pg_policies WHERE tablename IN "
                "('privacy_requests','privacy_request_events','data_deletion_tombstones')"
            )
        )
        worker_privacy_access = connection.scalar(
            text(
                "SELECT has_table_privilege(:worker, 'privacy_requests', 'SELECT') "
                "OR has_table_privilege(:worker, 'data_deletion_tombstones', 'SELECT')"
            ),
            {"worker": os.environ["OUTBOX_DB_USER"]},
        )
    assert revision == "20261104_18"
    assert delivery_policies == 4
    assert category_archived == "boolean"
    assert rate_limit_table == "rate_limit_buckets"
    assert app_rate_privileges is True
    assert worker_rate_privilege is False
    assert reconciliation_table == "hotmart_reconciliation_observations"
    assert app_reconciliation_users is True
    assert app_reconciliation_mutate is False
    assert worker_reconciliation_access is False
    assert lockout_table == "login_lockout_states"
    assert app_lockout_privileges is True
    assert worker_lockout_access is False
    assert idempotency_table == "idempotency_records"
    assert app_idempotency_privileges is True
    assert worker_idempotency_access is False
    assert idempotency_rls is True
    assert privacy_tables == 3
    assert privacy_policies >= 8
    assert worker_privacy_access is False
    assert "OLD.status = 'suspended'" in guard_definition
    assert support_tables == "support_operators"
    assert support_policies >= 1
