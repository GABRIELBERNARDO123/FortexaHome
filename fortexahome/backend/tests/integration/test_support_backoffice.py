from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import encrypt_text, email_lookup_hash, license_code_hash, license_code_last4
from app.core.rate_limit import limiter
from app.main import app
from app.models.email_outbox import EmailOutbox
from app.models.license import License
from app.models.order import Order
from app.models.product import Product
from app.services import license_service, support_service

pytestmark = pytest.mark.integration


@pytest.fixture
def admin_factory(integration_database):
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def disable_rate_limit(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)


def create_operator(
    email: str | None = None,
    *,
    role: str = "support_operator",
    status: str = "active",
) -> str:
    email = email or f"support-{uuid.uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        support_service.provision_support_operator(
            db,
            email=email,
            name="Operador de Suporte",
            role=role,
            password="SupportPass#2026",
            active=status == "active",
            apply=True,
        )
        db.commit()
    return email


def create_order(
    *,
    order_status: str = "paid",
    license_status: str = "pending",
    buyer_email: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID, str]:
    provider = f"support-provider-{uuid.uuid4().hex[:8]}"
    slug = f"support-product-{uuid.uuid4().hex[:8]}"
    code = f"FH-SUP-{uuid.uuid4().hex[:12].upper()}"
    buyer_email = buyer_email or f"buyer-{uuid.uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=slug,
            name="Produto suporte",
            price_cents=100,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.flush()
        set_db_context(db, payment_provider=provider)
        order = Order(
            provider=provider,
            external_order_id=f"tx-{uuid.uuid4()}",
            product_id=product.id,
            buyer_email_encrypted=encrypt_text(buyer_email, "orders.buyer_email"),
            buyer_email_hash=email_lookup_hash(buyer_email),
            amount_cents=100,
            currency="BRL",
            status=order_status,
        )
        db.add(order)
        db.flush()
        set_db_context(db, license_code_hash=license_code_hash(code))
        license_row = License(
            product_id=product.id,
            order_id=order.id,
            code_hash=license_code_hash(code),
            code_last4=license_code_last4(code),
            status=license_status,
            bound_email_hash=email_lookup_hash(buyer_email),
        )
        db.add(license_row)
        db.flush()
        db.commit()
        return order.id, license_row.id, buyer_email


def login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/support/auth/login",
        json={"email": email, "password": "SupportPass#2026"},
    )
    assert response.status_code == 200, response.text


def test_support_login_me_dashboard_and_customer_isolation():
    email = create_operator(role="support_read")
    with TestClient(app) as client:
        assert client.get("/api/v1/support/auth/me").status_code == 401
        login(client, email)
        me = client.get("/api/v1/support/auth/me")
        assert me.status_code == 200
        assert me.json()["operator"]["email"] == email
        assert me.json()["permissions"] == ["support:read"]
        assert client.get("/api/v1/support/dashboard").status_code == 200
        # Support cookie is not a customer cookie.
        assert client.get("/api/v1/auth/me").status_code == 401


def test_support_login_lockout_after_failures():
    email = create_operator(role="support_read")
    with TestClient(app) as client:
        for _ in range(5):
            response = client.post(
                "/api/v1/support/auth/login",
                json={"email": email, "password": "senha-errada"},
            )
            assert response.status_code == 401
        response = client.post(
            "/api/v1/support/auth/login",
            json={"email": email, "password": "SupportPass#2026"},
        )
        assert response.status_code == 401


def test_read_only_support_can_read_but_cannot_act():
    email = create_operator(role="support_read")
    order_id, license_id, _ = create_order()
    with TestClient(app) as client:
        login(client, email)
        assert client.get("/api/v1/support/orders").status_code == 200
        assert client.get(f"/api/v1/support/orders/{order_id}").status_code == 200
        assert client.get("/api/v1/support/licenses").status_code == 200
        assert client.get("/api/v1/support/outbox").status_code == 200
        assert client.get("/api/v1/support/audit").status_code == 200
        denied = client.post(
            f"/api/v1/support/orders/{order_id}/recovery-instructions",
            json={"justification": "Cliente solicitou recuperação pelo suporte"},
        )
        assert denied.status_code == 403


def test_support_operator_action_is_audited_and_idempotent(admin_factory):
    email = create_operator(role="support_operator")
    order_id, license_id, _ = create_order()
    with TestClient(app) as client:
        login(client, email)
        first = client.post(
            f"/api/v1/support/orders/{order_id}/recovery-instructions",
            json={"justification": "Cliente confirmou perda do e-mail original"},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/api/v1/support/orders/{order_id}/recovery-instructions",
            json={"justification": "Cliente confirmou perda do e-mail original"},
        )
        assert second.status_code == 409
        audit = client.get("/api/v1/support/audit").json()
    with admin_factory() as admin:
        count = admin.scalar(
            select(func.count()).select_from(EmailOutbox).where(
                EmailOutbox.event_type == "license_recovery_instructions",
                EmailOutbox.aggregate_id == license_id,
            )
        )
        assert count == 1
        status_value = admin.scalar(
            select(EmailOutbox.status).where(
                EmailOutbox.event_type == "license_recovery_instructions",
                EmailOutbox.aggregate_id == license_id,
            )
        )
        assert status_value == "pending"
    assert audit["total"] >= 2
    assert any(item["operation"] == "SUPPORT_RECOVERY_INSTRUCTIONS" for item in audit["items"])


def test_support_action_requires_justification():
    email = create_operator(role="support_operator")
    order_id, _, _ = create_order()
    with TestClient(app) as client:
        login(client, email)
        response = client.post(
            f"/api/v1/support/orders/{order_id}/recovery-instructions",
            json={"justification": "curta"},
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    ("order_status", "license_status"),
    [("refunded", "cancelled"), ("chargeback", "suspended"), ("cancelled", "cancelled")],
)
def test_support_action_rejects_terminal_order(admin_factory, order_status, license_status):
    email = create_operator(role="support_operator")
    order_id, license_id, _ = create_order(order_status=order_status, license_status=license_status)
    with TestClient(app) as client:
        login(client, email)
        response = client.post(
            f"/api/v1/support/orders/{order_id}/recovery-instructions",
            json={"justification": "Tentativa de recuperação para pedido terminal"},
        )
        assert response.status_code == 409
    with admin_factory() as admin:
        assert admin.scalar(
            select(func.count()).select_from(EmailOutbox).where(
                EmailOutbox.event_type == "license_recovery_instructions",
                EmailOutbox.aggregate_id == license_id,
            )
        ) == 0


def test_order_detail_masks_pii_and_never_exposes_hashes_or_payloads():
    email = create_operator(role="support_read")
    order_id, license_id, buyer_email = create_order()
    with TestClient(app) as client:
        login(client, email)
        response = client.get(f"/api/v1/support/orders/{order_id}")
        assert response.status_code == 200
        body = response.json()
        serialized = str(body)
        assert buyer_email not in serialized
        assert "code_hash" not in serialized
        assert "payload" not in serialized
        assert "••••" in body["license"]["code_last4"] or body["license"]["code_last4"]
        assert body["order"]["buyer_email_masked"] != buyer_email


def test_order_search_filter_and_pagination(admin_factory):
    email = create_operator(role="support_read")
    first_order, _, _ = create_order(buyer_email=f"filter-{uuid.uuid4().hex[:8]}@example.com")
    second_order, _, _ = create_order(buyer_email=f"filter-{uuid.uuid4().hex[:8]}@example.com")
    with admin_factory() as admin:
        first_tx = admin.scalar(select(Order.external_order_id).where(Order.id == first_order))
    with TestClient(app) as client:
        login(client, email)
        filtered = client.get("/api/v1/support/orders", params={"transaction": first_tx})
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["id"] == str(first_order)
        paged = client.get("/api/v1/support/orders", params={"page_size": 1})
        assert paged.status_code == 200
        assert len(paged.json()["items"]) == 1


def test_support_audit_is_append_only_for_app_role(integration_database):
    with SessionLocal() as db:
        with pytest.raises(DBAPIError):
            db.execute(text("UPDATE support_audit_logs SET result = 'tampered'"))
            db.commit()
        db.rollback()
        with pytest.raises(DBAPIError):
            db.execute(text("DELETE FROM support_audit_logs"))
            db.commit()
        db.rollback()


def test_support_operators_can_be_provisioned_updated_and_disabled():
    email = create_operator(role="support_read")
    with SessionLocal() as db:
        result = support_service.provision_support_operator(
            db,
            email=email,
            name="Outro nome",
            role="support_operator",
            password=None,
            active=False,
            apply=True,
        )
        db.commit()
    assert result["action"] == "updated"
    assert result["operator"]["role"] == "support_operator"
    assert result["operator"]["status"] == "disabled"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/support/auth/login",
            json={"email": email, "password": "SupportPass#2026"},
        )
        assert response.status_code == 401
