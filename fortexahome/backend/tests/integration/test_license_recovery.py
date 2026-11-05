from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import (
    decrypt_text,
    email_lookup_hash,
    encrypt_text,
    license_code_hash,
    license_code_last4,
    masked_email,
)
from app.core.security import hash_password
from app.models.email_outbox import EmailOutbox
from app.models.license import License
from app.models.order import Order
from app.models.pending_activation import PendingActivation
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.user import User
from app.services import activation_service, license_service

pytestmark = pytest.mark.integration


@pytest.fixture
def admin_factory(integration_database):
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def create_purchase(
    email: str,
    *,
    provider: str = "hotmart",
    order_status: str = "paid",
    license_status: str = "pending",
) -> tuple[uuid.UUID, uuid.UUID, str]:
    slug = f"recovery-{uuid.uuid4().hex[:12]}"
    code = f"FH-REC-{uuid.uuid4().hex[:12].upper()}"
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=slug,
            name="Produto recovery",
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
            external_order_id=f"order-{uuid.uuid4()}",
            product_id=product.id,
            buyer_email_encrypted=encrypt_text(email, "orders.buyer_email"),
            buyer_email_hash=email_lookup_hash(email),
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
            bound_email_hash=email_lookup_hash(email),
        )
        db.add(license_row)
        db.flush()
        db.commit()
        return order.id, license_row.id, code


def create_bound_user(email: str) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Bound tenant", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        db.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email_encrypted=encrypt_text(email, "users.email"),
                email_lookup_hash=email_lookup_hash(email),
                email_masked=masked_email(email),
                name_encrypted=encrypt_text("Pessoa", "users.name"),
                password_hash=hash_password("SenhaSegura#2026"),
                role="owner",
                status="active",
                theme="claro",
                email_verified_at=func.now(),
            )
        )
        db.commit()
    return tenant_id, user_id


def count_event(admin_factory, event_type: str) -> int:
    with admin_factory() as admin:
        return int(
            admin.scalar(
                select(func.count()).select_from(EmailOutbox).where(EmailOutbox.event_type == event_type)
            )
            or 0
        )


def latest_code_for_license(admin_factory, license_id: uuid.UUID) -> str:
    with admin_factory() as admin:
        activation = admin.scalar(
            select(PendingActivation)
            .where(PendingActivation.license_id == license_id)
            .order_by(PendingActivation.created_at.desc())
        )
        assert activation is not None
        event = admin.scalar(
            select(EmailOutbox)
            .where(EmailOutbox.aggregate_id == activation.id)
            .order_by(EmailOutbox.created_at.desc())
        )
        assert event is not None and event.payload_encrypted
        return json.loads(decrypt_text(event.payload_encrypted, "email_outbox.payload"))["code"]


def test_unbound_purchase_recovery_sends_code_and_creates_one_tenant(admin_factory):
    email = f"recover-{uuid.uuid4().hex[:8]}@example.com"
    _, license_id, _ = create_purchase(email)
    with SessionLocal() as db:
        result = activation_service.start_license_recovery(
            db,
            name="Comprador",
            email=email,
            password="SenhaSegura#2026",
        )
    assert result["message"]
    assert "activation_id" not in result
    code = latest_code_for_license(admin_factory, license_id)
    with admin_factory() as admin:
        activation = admin.scalar(select(PendingActivation).where(PendingActivation.license_id == license_id))
        assert activation is not None and activation.status == "pending"
    with SessionLocal() as db:
        _, auth = activation_service.confirm_license_recovery(db, email=email, code=code)
    assert auth["user"]["email"] == email
    assert auth["license"]["status"] == "active"
    with admin_factory() as admin:
        license_row = admin.get(License, license_id)
        assert license_row.tenant_id is not None
        assert admin.scalar(select(func.count()).select_from(User).where(User.tenant_id == license_row.tenant_id)) == 1
        assert admin.scalar(select(func.count()).select_from(Tenant).where(Tenant.id == license_row.tenant_id)) == 1


def test_unknown_email_is_generic_and_sends_nothing(admin_factory):
    email = f"unknown-{uuid.uuid4().hex[:8]}@example.com"
    before_events = count_event(admin_factory, "activation_verification")
    with admin_factory() as admin:
        before_pending = int(admin.scalar(select(func.count()).select_from(PendingActivation)) or 0)
    with SessionLocal() as db:
        result = activation_service.start_license_recovery(
            db,
            name="Comprador",
            email=email,
            password="SenhaSegura#2026",
        )
    assert result["message"]
    assert count_event(admin_factory, "activation_verification") == before_events
    with admin_factory() as admin:
        assert int(admin.scalar(select(func.count()).select_from(PendingActivation)) or 0) == before_pending


def test_existing_user_recovery_sends_password_reset_not_new_account(admin_factory):
    email = f"bound-{uuid.uuid4().hex[:8]}@example.com"
    tenant_id, user_id = create_bound_user(email)
    before_activation = count_event(admin_factory, "activation_verification")
    before_reset = count_event(admin_factory, "password_reset")
    with SessionLocal() as db:
        result = activation_service.start_license_recovery(
            db,
            name="Comprador",
            email=email,
            password="SenhaSegura#2026",
        )
    assert result["message"]
    assert count_event(admin_factory, "activation_verification") == before_activation
    assert count_event(admin_factory, "password_reset") >= before_reset + 1
    with admin_factory() as admin:
        assert admin.get(User, user_id).tenant_id == tenant_id


@pytest.mark.parametrize(
    ("order_status", "license_status"),
    [
        ("refunded", "cancelled"),
        ("chargeback", "suspended"),
        ("cancelled", "cancelled"),
        ("pending", "suspended"),
    ],
)
def test_recovery_rejects_terminal_or_suspended_purchase(admin_factory, order_status, license_status):
    email = f"blocked-{uuid.uuid4().hex[:8]}@example.com"
    create_purchase(email, order_status=order_status, license_status=license_status)
    before = count_event(admin_factory, "activation_verification")
    with SessionLocal() as db:
        result = activation_service.start_license_recovery(
            db,
            name="Comprador",
            email=email,
            password="SenhaSegura#2026",
        )
    assert result["message"]
    assert count_event(admin_factory, "activation_verification") == before


def test_recovery_cooldown_by_normalized_email(admin_factory):
    email = f"cooldown-{uuid.uuid4().hex[:8]}@example.com"
    create_purchase(email)
    before = count_event(admin_factory, "activation_verification")
    with SessionLocal() as db:
        activation_service.start_license_recovery(
            db, name="Comprador", email=email.upper(), password="SenhaSegura#2026"
        )
    with SessionLocal() as db:
        activation_service.start_license_recovery(
            db, name="Comprador", email=email, password="SenhaSegura#2026"
        )
    assert count_event(admin_factory, "activation_verification") == before + 1


def test_recovery_unknown_and_known_responses_have_same_shape(admin_factory):
    known = f"known-{uuid.uuid4().hex[:8]}@example.com"
    unknown = f"unknown-{uuid.uuid4().hex[:8]}@example.com"
    create_purchase(known)
    with SessionLocal() as db:
        first = activation_service.start_license_recovery(
            db, name="Comprador", email=known, password="SenhaSegura#2026"
        )
    with SessionLocal() as db:
        second = activation_service.start_license_recovery(
            db, name="Comprador", email=unknown, password="SenhaSegura#2026"
        )
    assert first == second


def test_recovery_works_when_original_delivery_is_dead(admin_factory):
    email = f"dead-recovery-{uuid.uuid4().hex[:8]}@example.com"
    _, license_id, license_code = create_purchase(email)
    from app.services import email_outbox_service

    with SessionLocal() as db:
        message = email_outbox_service.enqueue_email(
            db,
            event_type="license_delivery",
            payload={"to": email, "code": license_code, "product_name": "Produto recovery"},
            idempotency_key=f"dead-recovery:{uuid.uuid4()}",
            aggregate_id=license_id,
        )
        db.commit()
        message_id = message.id
    with admin_factory() as admin:
        admin.execute(text("UPDATE email_outbox SET status='dead' WHERE id=:id"), {"id": message_id})
        admin.commit()

    with SessionLocal() as db:
        activation_service.start_license_recovery(
            db, name="Comprador", email=email, password="SenhaSegura#2026"
        )
    code = latest_code_for_license(admin_factory, license_id)
    with SessionLocal() as db:
        _, auth = activation_service.confirm_license_recovery(db, email=email, code=code)
    assert auth["license"]["status"] == "active"


def test_recovery_http_flow_sets_session_only_after_confirmation(admin_factory, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.rate_limit import limiter
    from app.main import app

    monkeypatch.setattr(limiter, "enabled", False)
    email = f"http-recovery-{uuid.uuid4().hex[:8]}@example.com"
    _, license_id, _ = create_purchase(email)
    with TestClient(app) as client:
        started = client.post(
            "/api/v1/auth/recover-license",
            json={"name": "Comprador", "email": email, "password": "SenhaSegura#2026"},
        )
        assert started.status_code == 202, started.text
        assert "activation_id" not in started.text
        assert client.get("/api/v1/auth/me").status_code == 401
        code = latest_code_for_license(admin_factory, license_id)
        confirmed = client.post(
            "/api/v1/auth/recover-license/confirm",
            json={"email": email, "code": code},
        )
        assert confirmed.status_code == 201, confirmed.text
        assert "fh_session=" in confirmed.headers.get("set-cookie", "")
        assert client.get("/api/v1/auth/me").status_code == 200
