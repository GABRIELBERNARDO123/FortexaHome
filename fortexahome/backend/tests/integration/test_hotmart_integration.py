from __future__ import annotations

import json
import hashlib
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import decrypt_text, email_lookup_hash, license_code_hash
from fastapi.testclient import TestClient

from app.main import app
from app.models.email_outbox import EmailOutbox
from app.models.license import License
from app.models.order import Order
from app.models.payment_event import PaymentEvent
from app.models.product import Product
from app.models.tenant import Tenant
from app.services import activation_service, email_outbox_service, email_service, license_service
from app.integrations.payments.hotmart import parse_payload

pytestmark = pytest.mark.integration


@pytest.fixture
def admin_factory(integration_database):
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def hotmart_product(integration_database, monkeypatch):
    slug = f"hotmart-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(license_service.settings, "HOTMART_PRODUCT_SLUG", slug)
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=slug, name="Catálogo Fortexa teste", price_cents=12750,
            currency="BRL", license_kind="lifetime", active=True,
        )
        db.add(product)
        db.commit()
        product_id = product.id
    return slug, product_id


@pytest.fixture
def worker_factory(integration_database):
    url = make_url(os.environ["TEST_DATABASE_URL"]).set(
        username=os.environ["OUTBOX_DB_USER"],
        password=os.environ["OUTBOX_DB_PASSWORD"],
    )
    worker_engine = create_engine(url, pool_pre_ping=True)
    factory = sessionmaker(bind=worker_engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        worker_engine.dispose()


def payload(event: str, transaction: str, *, created_at: datetime | None = None,
            event_id: str | None = None, ucode: str = "UCODE-FICTICIO-001", buyer=True,
            buyer_email: str | None = None, order_bump: dict | None = None) -> bytes:
    created = created_at or datetime.now(timezone.utc)
    value = {
        "id": event_id or f"evt-{uuid.uuid4()}",
        "creation_date": int(created.timestamp() * 1000),
        "event": event,
        "version": "2.0.0",
        "data": {
            "product": {"ucode": ucode},
            "purchase": {
                "transaction": transaction,
                "status": event.removeprefix("PURCHASE_"),
                # These external commercial values must never override internal catalog.
                "price": {"value": 0.01, "currency_code": "USD"},
                "full_price": {"value": 0.02, "currency_code": "USD"},
            },
        },
    }
    if buyer:
        value["data"]["buyer"] = {
            "email": buyer_email or f"buyer-{uuid.uuid4().hex[:12]}@example.com",
            "name": "Comprador Fictício",
        }
    if order_bump is not None:
        value["data"]["purchase"]["order_bump"] = order_bump
    return json.dumps(value).encode()


def deliver(raw: bytes) -> dict:
    parsed = parse_payload(raw)
    with SessionLocal() as db:
        return license_service.process_hotmart_event(
            db, parsed, payload_hash=hashlib.sha256(raw).hexdigest()
        )


def test_approved_purchase_uses_catalog_and_commits_license_event_and_outbox(hotmart_product, admin_factory):
    slug, product_id = hotmart_product
    raw = payload("PURCHASE_APPROVED", f"tx-{uuid.uuid4()}")
    result = deliver(raw)
    assert result == {"status": "processed"}
    parsed = parse_payload(raw)
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == parsed.data.purchase.transaction))
        assert order is not None and order.status == "paid"
        assert order.product_id == product_id
        assert (order.amount_cents, order.currency) == (12750, "BRL")
        assert (order.provider_price_cents, order.provider_price_currency) == (1, "USD")
        assert (order.provider_full_price_cents, order.provider_full_price_currency) == (2, "USD")
        set_db_context(db, payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        event = db.scalar(select(PaymentEvent).where(PaymentEvent.external_event_id == parsed.id))
        assert license_row is not None and license_row.bound_email_hash is not None
        assert event is not None and event.order_id == order.id
    with admin_factory() as admin:
        email = admin.scalar(select(EmailOutbox).where(EmailOutbox.aggregate_id == license_row.id))
        assert email is not None and email.event_type == "license_delivery"
        assert parsed.data.buyer.email not in email.payload_encrypted


def test_event_and_transaction_deduplication_are_persistent(hotmart_product, admin_factory):
    raw = payload("PURCHASE_APPROVED", f"tx-{uuid.uuid4()}", event_id=f"event-{uuid.uuid4()}")
    assert deliver(raw)["status"] == "processed"
    assert deliver(raw)["status"] == "duplicate"
    parsed = parse_payload(raw)
    second_event = payload("PURCHASE_COMPLETE", parsed.data.purchase.transaction,
                           event_id=f"event-{uuid.uuid4()}", created_at=datetime.now(timezone.utc) + timedelta(seconds=1))
    assert deliver(second_event)["status"] == "processed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        orders = db.scalars(select(Order).where(Order.external_order_id == parsed.data.purchase.transaction)).all()
        assert len(orders) == 1
        set_db_context(db, payment_order_id=orders[0].id)
        assert len(db.scalars(select(License).where(License.order_id == orders[0].id)).all()) == 1
        license_id = db.scalar(select(License.id).where(License.order_id == orders[0].id))
    with admin_factory() as admin:
        assert len(admin.scalars(select(EmailOutbox).where(EmailOutbox.aggregate_id == license_id)).all()) == 1


def test_refund_cannot_be_undone_by_older_approval(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now, event_id=f"a-{uuid.uuid4()}"))["status"] == "processed"
    assert deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=10), event_id=f"r-{uuid.uuid4()}"))["status"] == "processed"
    result = deliver(payload("PURCHASE_APPROVED", transaction, created_at=now + timedelta(seconds=5), event_id=f"old-{uuid.uuid4()}"))
    assert result["status"] == "recorded"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order.status == "refunded"
        set_db_context(db, payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert license_row.status == "cancelled"


@pytest.mark.parametrize(
    ("event", "order_status", "license_status"),
    [
        ("PURCHASE_CHARGEBACK", "chargeback", "suspended"),
        ("PURCHASE_PROTEST", "chargeback", "suspended"),
        ("PURCHASE_CANCELED", "cancelled", "cancelled"),
        ("PURCHASE_EXPIRED", "cancelled", "cancelled"),
    ],
)
def test_negative_commercial_events_revoke_existing_license(hotmart_product, event, order_status, license_status):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))
    result = deliver(payload(event, transaction, created_at=now + timedelta(seconds=1)))
    assert result["status"] == "processed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order.status == order_status
        set_db_context(db, payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert license_row.status == license_status


def test_non_approval_events_never_issue_license(hotmart_product):
    for event in ("PURCHASE_CANCELED", "PURCHASE_DELAYED", "PURCHASE_EXPIRED", "PURCHASE_BILLET_PRINTED"):
        transaction = f"tx-{uuid.uuid4()}"
        assert deliver(payload(event, transaction))["status"] == "processed"
        with SessionLocal() as db:
            set_db_context(db, payment_provider="hotmart")
            order = db.scalar(select(Order).where(Order.external_order_id == transaction))
            assert order is not None
            set_db_context(db, payment_order_id=order.id)
            assert db.scalar(select(License).where(License.order_id == order.id)) is None


def test_approval_without_email_rolls_back_order_and_inbox(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    raw = payload("PURCHASE_APPROVED", transaction, buyer=False)
    with pytest.raises(Exception):
        deliver(raw)
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        assert db.scalar(select(Order).where(Order.external_order_id == transaction)) is None


def test_outbox_insert_failure_rolls_back_entire_hotmart_purchase(hotmart_product, monkeypatch):
    transaction = f"tx-{uuid.uuid4()}"
    raw = payload("PURCHASE_APPROVED", transaction)

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(email_outbox_service, "enqueue_email", fail_enqueue)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        deliver(raw)
    parsed = parse_payload(raw)
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        assert db.scalar(select(Order).where(Order.external_order_id == transaction)) is None
        assert db.scalar(select(PaymentEvent).where(PaymentEvent.external_event_id == parsed.id)) is None


def test_concurrent_duplicate_hotmart_event_creates_single_commercial_result(hotmart_product):
    raw = payload("PURCHASE_APPROVED", f"tx-{uuid.uuid4()}", event_id=f"event-{uuid.uuid4()}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: deliver(raw), range(2)))
    assert sorted(result["status"] for result in results) == ["duplicate", "processed"]
    parsed = parse_payload(raw)
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == parsed.data.purchase.transaction))
        assert order is not None
        set_db_context(db, payment_order_id=order.id)
        assert len(db.scalars(select(License).where(License.order_id == order.id)).all()) == 1
        assert len(db.scalars(select(PaymentEvent).where(PaymentEvent.order_id == order.id)).all()) == 1


def test_concurrent_distinct_events_for_one_transaction_share_one_license(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    events = [
        payload("PURCHASE_APPROVED", transaction, event_id=f"event-{uuid.uuid4()}")
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(deliver, events))
    assert all(result["status"] in {"processed", "recorded"} for result in results)
    assert "processed" in {result["status"] for result in results}
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order is not None
        set_db_context(db, payment_order_id=order.id)
        license_id = db.scalar(select(License.id).where(License.order_id == order.id))
        assert license_id is not None
        assert len(db.scalars(select(PaymentEvent).where(PaymentEvent.order_id == order.id)).all()) == 2
    with admin_factory() as admin:
        assert len(admin.scalars(select(EmailOutbox).where(EmailOutbox.aggregate_id == license_id)).all()) == 1


def test_http_endpoint_authenticates_and_ignores_unconfigured_product(hotmart_product, monkeypatch):
    _, _ = hotmart_product
    settings = license_service.settings
    monkeypatch.setattr(settings, "HOTMART_ENABLED", True)
    monkeypatch.setattr(settings, "HOTMART_WEBHOOK_HOTTOK", "test-only-hotmart-hottok-value")
    monkeypatch.setattr(settings, "HOTMART_PRODUCT_UCODE", "UCODE-FICTICIO-001")
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/webhooks/hotmart", json={})
        assert unauthorized.status_code == 401, unauthorized.text
        bad = client.post("/api/v1/webhooks/hotmart", headers={"X-HOTMART-HOTTOK": "wrong"}, json={})
        assert bad.status_code == 401
        accepted = json.loads(payload("PURCHASE_APPROVED", f"tx-{uuid.uuid4()}", ucode="OUTRO-UCODE"))
        ignored = client.post(
            "/api/v1/webhooks/hotmart",
            headers={"X-HOTMART-HOTTOK": "test-only-hotmart-hottok-value"},
            json=accepted,
        )
        assert ignored.status_code == 200
        assert ignored.json() == {"status": "ignored"}
        invalid_type = client.post(
            "/api/v1/webhooks/hotmart",
            headers={"X-HOTMART-HOTTOK": "test-only-hotmart-hottok-value", "Content-Type": "text/plain"},
            content=b"{}",
        )
        assert invalid_type.status_code == 415
        invalid_json = client.post(
            "/api/v1/webhooks/hotmart",
            headers={"X-HOTMART-HOTTOK": "test-only-hotmart-hottok-value", "Content-Type": "application/json"},
            content=b"{invalid",
        )
        assert invalid_json.status_code == 400
        oversized = client.post(
            "/api/v1/webhooks/hotmart",
            headers={"X-HOTMART-HOTTOK": "test-only-hotmart-hottok-value", "Content-Type": "application/json"},
            content=b" " * (256 * 1024 + 1),
        )
        assert oversized.status_code == 413
        transaction = f"tx-{uuid.uuid4()}"
        valid = client.post(
            "/api/v1/webhooks/hotmart",
            headers={
                "X-HOTMART-HOTTOK": "test-only-hotmart-hottok-value",
                "Content-Type": "application/json",
            },
            content=payload("PURCHASE_APPROVED", transaction, ucode="UCODE-FICTICIO-001"),
        )
        assert valid.status_code == 200
        assert valid.json() == {"status": "processed"}


def test_same_timestamp_uses_state_precedence(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    delayed = deliver(payload("PURCHASE_DELAYED", transaction, created_at=now))
    assert delayed["status"] == "recorded"
    refunded = deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now))
    assert refunded["status"] == "processed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order.status == "refunded"
        set_db_context(db, payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert license_row.status == "cancelled"


@pytest.mark.parametrize(
    ("event", "order_status", "license_status"),
    [
        ("PURCHASE_CHARGEBACK", "chargeback", "suspended"),
        ("PURCHASE_CANCELED", "cancelled", "cancelled"),
        ("PURCHASE_EXPIRED", "cancelled", "cancelled"),
    ],
)
def test_negative_event_cannot_be_undone_by_older_approval(
    hotmart_product, event, order_status, license_status
):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    assert deliver(payload(event, transaction, created_at=now + timedelta(seconds=10)))["status"] == "processed"
    assert deliver(
        payload("PURCHASE_APPROVED", transaction, created_at=now + timedelta(seconds=5))
    )["status"] == "recorded"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order.status == order_status
        set_db_context(db, payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert license_row.status == license_status


def test_order_bump_same_product_uses_its_own_transaction(hotmart_product):
    main_transaction = f"tx-{uuid.uuid4()}"
    bump_transaction = f"tx-{uuid.uuid4()}"
    assert deliver(payload("PURCHASE_APPROVED", main_transaction))["status"] == "processed"
    assert deliver(payload(
        "PURCHASE_APPROVED",
        bump_transaction,
        order_bump={"is_order_bump": True, "parent_purchase_transaction": main_transaction},
    ))["status"] == "processed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        orders = db.scalars(
            select(Order).where(Order.external_order_id.in_([main_transaction, bump_transaction]))
        ).all()
        assert {order.external_order_id for order in orders} == {main_transaction, bump_transaction}
        for order in orders:
            set_db_context(db, payment_order_id=order.id)
            assert db.scalar(select(License).where(License.order_id == order.id)) is not None


def test_order_bump_empty_parent_is_keyed_by_own_transaction(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    raw = payload(
        "PURCHASE_APPROVED",
        transaction,
        order_bump={"is_order_bump": True, "parent_purchase_transaction": ""},
    )
    assert deliver(raw)["status"] == "processed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order is not None and order.status == "paid"
        assert db.scalar(select(Order).where(Order.external_order_id == "")) is None


def test_order_bump_parent_is_not_used_as_substitute_order_key(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    parent = f"parent-{uuid.uuid4()}"
    raw = payload(
        "PURCHASE_APPROVED",
        transaction,
        order_bump={"is_order_bump": True, "parent_purchase_transaction": parent},
    )
    assert deliver(raw)["status"] == "processed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        assert db.scalar(select(Order).where(Order.external_order_id == transaction)) is not None
        assert db.scalar(select(Order).where(Order.external_order_id == parent)) is None


def test_order_bump_of_another_product_is_ignored(hotmart_product, monkeypatch):
    settings = license_service.settings
    monkeypatch.setattr(settings, "HOTMART_ENABLED", True)
    monkeypatch.setattr(settings, "HOTMART_WEBHOOK_HOTTOK", "test-only-hotmart-hottok-value")
    monkeypatch.setattr(settings, "HOTMART_PRODUCT_UCODE", "UCODE-FICTICIO-001")
    transaction = f"tx-{uuid.uuid4()}"
    raw = payload(
        "PURCHASE_APPROVED",
        transaction,
        ucode="OUTRO-PRODUTO-UCODE",
        order_bump={"is_order_bump": True, "parent_purchase_transaction": f"parent-{uuid.uuid4()}"},
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/webhooks/hotmart",
            headers={
                "X-HOTMART-HOTTOK": "test-only-hotmart-hottok-value",
                "Content-Type": "application/json",
            },
            content=raw,
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        assert db.scalar(select(Order).where(Order.external_order_id == transaction)) is None


def commercial_state(transaction: str):
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        if order is None:
            return None
        set_db_context(db, payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        return {
            "order_id": order.id,
            "order_status": order.status,
            "license_id": license_row.id if license_row else None,
            "license_status": license_row.status if license_row else None,
            "revoked_at": license_row.revoked_at if license_row else None,
            "tenant_id": license_row.tenant_id if license_row else None,
        }


def delivery_for(admin, license_id: uuid.UUID) -> EmailOutbox:
    return admin.scalar(
        select(EmailOutbox).where(
            EmailOutbox.event_type == "license_delivery",
            EmailOutbox.aggregate_id == license_id,
        )
    )


def test_delayed_then_newer_approval_recovers_unactivated_license(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    buyer_email = f"recovery-{uuid.uuid4().hex[:8]}@example.com"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now, buyer_email=buyer_email))["status"] == "processed"
    assert deliver(payload("PURCHASE_DELAYED", transaction, created_at=now + timedelta(seconds=1), buyer_email=buyer_email))["status"] == "processed"
    state = commercial_state(transaction)
    assert state["order_status"] == "pending"
    assert state["license_status"] == "suspended"
    with admin_factory() as admin:
        assert delivery_for(admin, state["license_id"]).status == "pending"

    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now + timedelta(seconds=2), buyer_email=buyer_email))["status"] == "processed"
    state = commercial_state(transaction)
    assert state["order_status"] == "paid"
    assert state["license_status"] == "pending"
    assert state["revoked_at"] is None
    with admin_factory() as admin:
        assert delivery_for(admin, state["license_id"]).status == "pending"


def test_delayed_then_newer_approval_recovers_activated_license(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    buyer_email = f"activated-{uuid.uuid4().hex[:8]}@example.com"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now, buyer_email=buyer_email))["status"] == "processed"
    state = commercial_state(transaction)
    with admin_factory() as admin:
        delivery = delivery_for(admin, state["license_id"])
        code = json.loads(decrypt_text(delivery.payload_encrypted, "email_outbox.payload"))["code"]

    tenant_id = uuid.uuid4()
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Ativada", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        set_db_context(db, license_code_hash=license_code_hash(code))
        license_row = db.scalar(select(License).where(License.id == state["license_id"]))
        license_service.bind_license(db, license_row, tenant_id, email_lookup_hash(buyer_email))
        db.commit()

    assert deliver(payload("PURCHASE_DELAYED", transaction, created_at=now + timedelta(seconds=1), buyer_email=buyer_email))["status"] == "processed"
    assert commercial_state(transaction)["license_status"] == "suspended"
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now + timedelta(seconds=2), buyer_email=buyer_email))["status"] == "processed"
    state = commercial_state(transaction)
    assert state["order_status"] == "paid"
    assert state["license_status"] == "active"
    assert state["tenant_id"] == tenant_id
    assert state["revoked_at"] is None


def test_older_delayed_does_not_suspend_paid_order(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    assert deliver(payload("PURCHASE_DELAYED", transaction, created_at=now - timedelta(seconds=1)))["status"] == "recorded"
    state = commercial_state(transaction)
    assert state["order_status"] == "paid"
    assert state["license_status"] == "pending"


def test_same_timestamp_delayed_then_approval_uses_precedence(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_DELAYED", transaction, created_at=now))["status"] == "processed"
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    state = commercial_state(transaction)
    assert state["order_status"] == "paid"
    assert state["license_status"] == "pending"


@pytest.mark.parametrize(
    ("event", "order_status", "license_status"),
    [
        ("PURCHASE_REFUNDED", "refunded", "cancelled"),
        ("PURCHASE_CHARGEBACK", "chargeback", "suspended"),
        ("PURCHASE_PROTEST", "chargeback", "suspended"),
        ("PURCHASE_CANCELED", "cancelled", "cancelled"),
        ("PURCHASE_EXPIRED", "cancelled", "cancelled"),
    ],
)
def test_terminal_event_blocks_even_newer_approval(hotmart_product, event, order_status, license_status):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    assert deliver(payload(event, transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    assert deliver(
        payload("PURCHASE_APPROVED", transaction, created_at=now + timedelta(seconds=2))
    )["status"] == "recorded"
    state = commercial_state(transaction)
    assert state["order_status"] == order_status
    assert state["license_status"] == license_status


def test_concurrent_approval_and_refund_end_refunded(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    events = [
        payload("PURCHASE_APPROVED", transaction, created_at=now),
        payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=1)),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(deliver, events))
    state = commercial_state(transaction)
    assert state["order_status"] == "refunded"
    if state["license_id"] is not None:
        assert state["license_status"] == "cancelled"
        with admin_factory() as admin:
            delivery = admin.scalar(
                select(EmailOutbox).where(
                    EmailOutbox.event_type == "license_delivery",
                    EmailOutbox.aggregate_id == state["license_id"],
                )
            )
            if delivery is not None:
                assert delivery.status in {"cancelled", "sent"}


def test_concurrent_approval_and_cancel_end_cancelled(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    events = [
        payload("PURCHASE_APPROVED", transaction, created_at=now),
        payload("PURCHASE_CANCELED", transaction, created_at=now + timedelta(seconds=1)),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(deliver, events))
    state = commercial_state(transaction)
    assert state["order_status"] == "cancelled"
    if state["license_id"] is not None:
        assert state["license_status"] == "cancelled"


def test_concurrent_approval_and_chargeback_end_chargeback(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    events = [
        payload("PURCHASE_APPROVED", transaction, created_at=now),
        payload("PURCHASE_CHARGEBACK", transaction, created_at=now + timedelta(seconds=1)),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(deliver, events))
    state = commercial_state(transaction)
    assert state["order_status"] == "chargeback"
    if state["license_id"] is not None:
        assert state["license_status"] == "suspended"
        with admin_factory() as admin:
            delivery = admin.scalar(
                select(EmailOutbox).where(
                    EmailOutbox.event_type == "license_delivery",
                    EmailOutbox.aggregate_id == state["license_id"],
                )
            )
            if delivery is not None:
                assert delivery.status in {"cancelled", "sent"}


def test_concurrent_delayed_and_approval_respects_timestamp(hotmart_product):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    events = [
        payload("PURCHASE_DELAYED", transaction, created_at=now),
        payload("PURCHASE_APPROVED", transaction, created_at=now + timedelta(seconds=1)),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(deliver, events))
    state = commercial_state(transaction)
    assert state["order_status"] == "paid"
    assert state["license_status"] in {"pending", "active"}


def test_refund_cancels_pending_license_delivery(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    state = commercial_state(transaction)
    with admin_factory() as admin:
        delivery = delivery_for(admin, state["license_id"])
        assert delivery.status == "pending"
        delivery_id = delivery.id
    assert deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    state = commercial_state(transaction)
    assert state["order_status"] == "refunded"
    assert state["license_status"] == "cancelled"
    with admin_factory() as admin:
        delivery = admin.get(EmailOutbox, delivery_id)
        assert delivery.status == "cancelled"
        assert delivery.payload_encrypted is None
        assert delivery.last_error == "license_revoked"


def test_chargeback_cancels_pending_license_delivery(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    state = commercial_state(transaction)
    with admin_factory() as admin:
        delivery_id = delivery_for(admin, state["license_id"]).id
    assert deliver(payload("PURCHASE_CHARGEBACK", transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    with admin_factory() as admin:
        delivery = admin.get(EmailOutbox, delivery_id)
        assert delivery.status == "cancelled"
        assert delivery.payload_encrypted is None
        assert delivery.last_error == "license_suspended"


def test_refund_does_not_cancel_other_order_or_password_reset(hotmart_product, admin_factory):
    now = datetime.now(timezone.utc)
    first_transaction = f"tx-{uuid.uuid4()}"
    second_transaction = f"tx-{uuid.uuid4()}"
    assert deliver(payload("PURCHASE_APPROVED", first_transaction, created_at=now))["status"] == "processed"
    assert deliver(payload("PURCHASE_APPROVED", second_transaction, created_at=now))["status"] == "processed"
    first_state = commercial_state(first_transaction)
    second_state = commercial_state(second_transaction)
    with SessionLocal() as app:
        reset = email_outbox_service.enqueue_email(
            app,
            event_type="password_reset",
            payload={"to": "reset@example.test", "token": "reset-token"},
            idempotency_key=f"reset-test:{uuid.uuid4()}",
            aggregate_id=uuid.uuid4(),
        )
        app.commit()
        reset_id = reset.id
    assert deliver(payload("PURCHASE_REFUNDED", first_transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    with admin_factory() as admin:
        assert admin.get(EmailOutbox, delivery_for(admin, first_state["license_id"]).id).status == "cancelled"
        assert delivery_for(admin, second_state["license_id"]).status == "pending"
        assert admin.get(EmailOutbox, reset_id).status == "pending"


def test_chargeback_does_not_cancel_other_order_or_password_reset(hotmart_product, admin_factory):
    now = datetime.now(timezone.utc)
    first_transaction = f"tx-{uuid.uuid4()}"
    second_transaction = f"tx-{uuid.uuid4()}"
    assert deliver(payload("PURCHASE_APPROVED", first_transaction, created_at=now))["status"] == "processed"
    assert deliver(payload("PURCHASE_APPROVED", second_transaction, created_at=now))["status"] == "processed"
    first_state = commercial_state(first_transaction)
    second_state = commercial_state(second_transaction)
    with SessionLocal() as app:
        reset = email_outbox_service.enqueue_email(
            app,
            event_type="password_reset",
            payload={"to": "reset@example.test", "token": "reset-token"},
            idempotency_key=f"reset-test:{uuid.uuid4()}",
            aggregate_id=uuid.uuid4(),
        )
        app.commit()
        reset_id = reset.id
    assert deliver(payload("PURCHASE_CHARGEBACK", first_transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    with admin_factory() as admin:
        assert admin.get(EmailOutbox, delivery_for(admin, first_state["license_id"]).id).status == "cancelled"
        assert delivery_for(admin, second_state["license_id"]).status == "pending"
        assert admin.get(EmailOutbox, reset_id).status == "pending"


def test_sent_delivery_is_not_altered_by_refund(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    state = commercial_state(transaction)
    with admin_factory() as admin:
        delivery = delivery_for(admin, state["license_id"])
        delivery_id = delivery.id
        admin.execute(
            text("UPDATE email_outbox SET status='sent', sent_at=now(), processed_at=now() WHERE id=:id"),
            {"id": delivery_id},
        )
        admin.commit()
    assert deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    with admin_factory() as admin:
        delivery = admin.get(EmailOutbox, delivery_id)
        assert delivery.status == "sent"
        assert delivery.sent_at is not None


def test_repeated_refund_keeps_delivery_cancelled_and_single_message(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    state = commercial_state(transaction)
    assert deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    assert deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=2)))["status"] == "recorded"
    with admin_factory() as admin:
        deliveries = admin.scalars(
            select(EmailOutbox).where(
                EmailOutbox.event_type == "license_delivery",
                EmailOutbox.aggregate_id == state["license_id"],
            )
        ).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "cancelled"
        assert deliveries[0].payload_encrypted is None


def test_refund_after_worker_reserved_cancels_processing_delivery(
    hotmart_product, admin_factory, worker_factory, monkeypatch
):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now))["status"] == "processed"
    state = commercial_state(transaction)
    with admin_factory() as admin:
        delivery_id = delivery_for(admin, state["license_id"]).id
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert delivery_id in email_outbox_service.claim_batch(worker, worker_id, batch_size=1000)
    assert deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=1)))["status"] == "processed"
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args))
    with worker_factory() as worker:
        assert email_outbox_service.process_one(worker, delivery_id, worker_id) == "cancelled"
    assert delivered == []
    with admin_factory() as admin:
        delivery = admin.get(EmailOutbox, delivery_id)
        assert delivery.status == "cancelled"
        assert delivery.payload_encrypted is None


def test_refund_while_worker_is_sending_keeps_sent_and_cancels_license(
    hotmart_product, admin_factory, worker_factory, monkeypatch
):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    buyer_email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now, buyer_email=buyer_email))["status"] == "processed"
    state = commercial_state(transaction)
    with admin_factory() as admin:
        delivery_id = delivery_for(admin, state["license_id"]).id

    provider_started = threading.Event()
    release_provider = threading.Event()
    delivered = []

    def blocking_provider(*args, **kwargs):
        delivered.append(args)
        provider_started.set()
        assert release_provider.wait(10)
        return "provider-message-id"

    monkeypatch.setattr(email_service, "send_rendered_email", blocking_provider)
    worker_id = uuid.uuid4()
    worker_results = []
    refund_results = []

    def run_worker():
        with worker_factory() as worker:
            assert delivery_id in email_outbox_service.claim_batch(worker, worker_id, batch_size=1000)
            worker_results.append(email_outbox_service.process_one(worker, delivery_id, worker_id))

    def run_refund():
        refund_results.append(
            deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=1), buyer_email=buyer_email))
        )

    worker_thread = threading.Thread(target=run_worker)
    worker_thread.start()
    assert provider_started.wait(10)
    refund_thread = threading.Thread(target=run_refund)
    refund_thread.start()
    time.sleep(0.3)
    release_provider.set()
    worker_thread.join(10)
    refund_thread.join(10)

    assert not worker_thread.is_alive()
    assert not refund_thread.is_alive()
    assert worker_results == ["sent"]
    assert refund_results == [{"status": "processed"}]
    assert len(delivered) == 1
    state = commercial_state(transaction)
    assert state["order_status"] == "refunded"
    assert state["license_status"] == "cancelled"
    with admin_factory() as admin:
        delivery = admin.get(EmailOutbox, delivery_id)
        assert delivery.status == "sent"
        assert delivery.provider_message_id == "provider-message-id"


def test_cancelled_license_blocks_activation_after_delivery_was_sent(hotmart_product, admin_factory):
    transaction = f"tx-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    buyer_email = f"blocked-{uuid.uuid4().hex[:8]}@example.com"
    assert deliver(payload("PURCHASE_APPROVED", transaction, created_at=now, buyer_email=buyer_email))["status"] == "processed"
    state = commercial_state(transaction)
    with admin_factory() as admin:
        delivery = delivery_for(admin, state["license_id"])
        code = json.loads(decrypt_text(delivery.payload_encrypted, "email_outbox.payload"))["code"]
        admin.execute(
            text("UPDATE email_outbox SET status='sent', sent_at=now(), processed_at=now() WHERE id=:id"),
            {"id": delivery.id},
        )
        admin.commit()
    assert deliver(payload("PURCHASE_REFUNDED", transaction, created_at=now + timedelta(seconds=1), buyer_email=buyer_email))["status"] == "processed"

    with SessionLocal() as db:
        with pytest.raises(HTTPException):
            activation_service.start_activation(
                db,
                name="Comprador",
                email=buyer_email,
                password="SenhaSegura#2026",
                license_code=code,
            )
