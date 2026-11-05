from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import email_lookup_hash, encrypt_text
from app.integrations.payments.hotmart import parse_payload
from app.integrations.payments.hotmart_api import (
    HotmartAuthError,
    HotmartTransactionObservation,
)
from app.models.email_outbox import EmailOutbox
from app.models.hotmart_reconciliation import HotmartReconciliationObservation
from app.models.license import License
from app.models.order import Order
from app.models.product import Product
from app.services import license_service
from app.services.hotmart_reconciliation_service import reconcile_transaction

pytestmark = pytest.mark.integration
PRODUCT_ID = 1234567


@pytest.fixture
def admin_factory(integration_database):
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def reconciliation_env(integration_database, monkeypatch):
    slug = f"hotmart-recon-{uuid.uuid4().hex}"
    ucode = f"UCODE-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(license_service.settings, "HOTMART_PRODUCT_SLUG", slug)
    monkeypatch.setattr(license_service.settings, "HOTMART_PRODUCT_UCODE", ucode)
    monkeypatch.setattr(license_service.settings, "HOTMART_RECONCILIATION_PRODUCT_ID", str(PRODUCT_ID))
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=slug,
            name="Produto reconciliação",
            price_cents=19990,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.commit()
        return {"slug": slug, "ucode": ucode, "product_id": product.id}


def webhook_payload(event: str, transaction: str, *, email: str | None = None,
                    created_at: datetime | None = None, event_id: str | None = None) -> bytes:
    created = created_at or datetime.now(timezone.utc)
    value = {
        "id": event_id or f"evt-{uuid.uuid4()}",
        "creation_date": int(created.timestamp() * 1000),
        "event": event,
        "version": "2.0.0",
        "data": {
            "product": {"ucode": license_service.settings.HOTMART_PRODUCT_UCODE},
            "purchase": {"transaction": transaction, "status": event.removeprefix("PURCHASE_")},
        },
    }
    if email:
        value["data"]["buyer"] = {"email": email}
    return json.dumps(value).encode()


def deliver(event: str, transaction: str, *, email: str | None = None,
            created_at: datetime | None = None) -> None:
    raw = webhook_payload(event, transaction, email=email, created_at=created_at)
    with SessionLocal() as db:
        license_service.process_hotmart_event(
            db,
            parse_payload(raw),
            payload_hash=hashlib.sha256(raw).hexdigest(),
        )


def create_pending_order(product_id, transaction: str, *, email: str | None = None) -> uuid.UUID:
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = Order(
            provider="hotmart",
            external_order_id=transaction,
            product_id=product_id,
            buyer_email_encrypted=encrypt_text(email, "orders.buyer_email") if email else None,
            buyer_email_hash=email_lookup_hash(email) if email else None,
            amount_cents=19990,
            currency="BRL",
            status="pending",
        )
        db.add(order)
        db.commit()
        return order.id


def observation(status: str, *, product_id: int | None = PRODUCT_ID, transaction: str = "TX") -> HotmartTransactionObservation:
    return HotmartTransactionObservation(
        transaction=transaction,
        status=status,
        product_id=product_id,
        product_name="Produto",
        product_ucode=None,
        order_date=datetime.now(timezone.utc) - timedelta(days=1),
        approved_date=None,
        price_cents=None,
        price_currency=None,
    )


class FakeClient:
    def __init__(self, result=None, *, error=None, on_fetch=None, barrier=None, transaction="TX"):
        self.result = result
        self.error = error
        self.on_fetch = on_fetch
        self.barrier = barrier
        self.transaction = transaction

    def fetch_transaction(self, transaction: str):
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        if self.on_fetch is not None:
            self.on_fetch(transaction)
        if self.error is not None:
            raise self.error
        if self.result is None:
            return None
        return HotmartTransactionObservation(
            transaction=transaction,
            status=self.result.status,
            product_id=self.result.product_id,
            product_name=self.result.product_name,
            product_ucode=self.result.product_ucode,
            order_date=self.result.order_date,
            approved_date=self.result.approved_date,
            price_cents=self.result.price_cents,
            price_currency=self.result.price_currency,
        )


def observations(run_id: uuid.UUID) -> list[HotmartReconciliationObservation]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(HotmartReconciliationObservation)
                .where(HotmartReconciliationObservation.run_id == run_id)
                .order_by(HotmartReconciliationObservation.created_at)
            )
        )


def test_missed_approval_creates_license_and_delivery_from_existing_local_order(
    reconciliation_env, admin_factory
):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    order_id = create_pending_order(reconciliation_env["product_id"], transaction, email=email)
    run_id = uuid.uuid4()

    result = reconcile_transaction(
        transaction,
        run_id=run_id,
        client=FakeClient(observation("APPROVED")),
        dry_run=False,
    )
    assert result.application_result == "applied"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart", payment_order_id=order_id)
        order = db.get(Order, order_id)
        license_row = db.scalar(select(License).where(License.order_id == order_id))
        assert order.status == "paid"
        assert license_row is not None and license_row.status == "pending"
        assert license_row.bound_email_hash == email_lookup_hash(email)
    with admin_factory() as admin:
        delivery = admin.scalar(select(EmailOutbox).where(EmailOutbox.aggregate_id == license_row.id))
        assert delivery is not None and delivery.event_type == "license_delivery"
    rows = observations(run_id)
    assert len(rows) == 1
    assert rows[0].comparison_result == "correctable"
    assert rows[0].application_result == "applied"
    assert rows[0].source == "hotmart_sales_api"


def test_missed_approval_restores_temporarily_suspended_license(reconciliation_env):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    deliver("PURCHASE_APPROVED", transaction, email=email, created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    deliver("PURCHASE_DELAYED", transaction, email=email, created_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
        assert order.status == "pending"
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert license_row.status == "suspended"

    result = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation("APPROVED")),
        dry_run=False,
    )
    assert result.application_result == "applied"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert order.status == "paid"
        assert license_row.status == "pending"
        assert license_row.revoked_at is None


@pytest.mark.parametrize(
    ("remote_status", "expected_order", "expected_license"),
    [
        ("REFUNDED", "refunded", "cancelled"),
        ("CHARGEBACK", "chargeback", "suspended"),
        ("PROTESTED", "chargeback", "suspended"),
        ("CANCELLED", "cancelled", "cancelled"),
        ("EXPIRED", "cancelled", "cancelled"),
    ],
)
def test_terminal_remote_state_cancels_paid_order_and_delivery(
    reconciliation_env, admin_factory, remote_status, expected_order, expected_license
):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    deliver("PURCHASE_APPROVED", transaction, email=email, created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        order_id = order.id
        set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        license_id = license_row.id

    result = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation(remote_status)),
        dry_run=False,
    )
    assert result.application_result == "applied"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart", payment_order_id=order_id)
        order = db.get(Order, order_id)
        license_row = db.get(License, license_id)
        assert order.status == expected_order
        assert license_row.status == expected_license
    with admin_factory() as admin:
        delivery = admin.scalar(select(EmailOutbox).where(EmailOutbox.aggregate_id == license_id))
        assert delivery is not None and delivery.status == "cancelled"


def test_terminal_local_state_is_never_reopened_by_remote_approval(reconciliation_env):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    deliver("PURCHASE_APPROVED", transaction, email=email, created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    deliver("PURCHASE_REFUNDED", transaction, email=email, created_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    result = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation("APPROVED")),
        dry_run=False,
    )
    assert result.comparison_result == "manual_review"
    assert result.application_result == "rejected"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert order.status == "refunded"
        assert license_row.status == "cancelled"


@pytest.mark.parametrize("remote_status", ["BLOCKED", "PARTIALLY_REFUNDED", "NO_FUNDS", "ALIEN_STATUS"])
def test_unsafe_or_unknown_remote_states_require_manual_review(reconciliation_env, remote_status):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    deliver("PURCHASE_APPROVED", transaction, email=email, created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    result = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation(remote_status)),
        dry_run=False,
    )
    assert result.comparison_result == "manual_review"
    assert result.application_result == "rejected"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order.status == "paid"


def test_dry_run_compares_without_changing_state(reconciliation_env, admin_factory):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    deliver("PURCHASE_APPROVED", transaction, email=email, created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    run_id = uuid.uuid4()
    result = reconcile_transaction(
        transaction,
        run_id=run_id,
        client=FakeClient(observation("REFUNDED")),
        dry_run=True,
    )
    assert result.application_result == "dry_run"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        assert order.status == "paid"
        assert license_row.status == "pending"
    rows = observations(run_id)
    assert len(rows) == 1 and rows[0].dry_run is True


def test_local_order_missing_is_never_created(reconciliation_env):
    transaction = f"TX-{uuid.uuid4()}"
    run_id = uuid.uuid4()
    result = reconcile_transaction(
        transaction,
        run_id=run_id,
        client=FakeClient(observation("APPROVED")),
        dry_run=False,
    )
    assert result.comparison_result == "local_order_missing"
    assert result.application_result == "rejected"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order).where(Order.external_order_id == transaction)) == 0
    rows = observations(run_id)
    assert len(rows) == 1 and rows[0].order_id is None


def test_product_mismatch_requires_manual_review(reconciliation_env):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    create_pending_order(reconciliation_env["product_id"], transaction, email=email)
    result = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation("APPROVED", product_id=9999999)),
        dry_run=False,
    )
    assert result.comparison_result == "manual_review"
    assert result.reason == "remote_product_mismatch"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
        assert order.status == "pending"
        assert db.scalar(select(func.count()).select_from(License).where(License.order_id == order.id)) == 0


def test_api_error_does_not_change_commercial_state(reconciliation_env):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    create_pending_order(reconciliation_env["product_id"], transaction, email=email)
    run_id = uuid.uuid4()
    result = reconcile_transaction(
        transaction,
        run_id=run_id,
        client=FakeClient(error=HotmartAuthError("falha", code="invalid_token")),
        dry_run=False,
    )
    assert result.comparison_result == "error"
    assert result.application_result == "failed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order.status == "pending"
    rows = observations(run_id)
    assert len(rows) == 1 and rows[0].error_code == "invalid_token"


def test_reprocessing_is_idempotent(reconciliation_env, admin_factory):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    order_id = create_pending_order(reconciliation_env["product_id"], transaction, email=email)
    first = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation("APPROVED")),
        dry_run=False,
    )
    second = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation("APPROVED")),
        dry_run=False,
    )
    assert first.application_result == "applied"
    assert second.application_result == "no_change"
    assert second.comparison_result == "consistent"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart", payment_order_id=order_id)
        assert db.scalar(select(func.count()).select_from(License).where(License.order_id == order_id)) == 1
        license_id = db.scalar(select(License.id).where(License.order_id == order_id))
    with admin_factory() as admin:
        assert admin.scalar(select(func.count()).select_from(EmailOutbox).where(EmailOutbox.aggregate_id == license_id)) == 1


def test_stale_observation_does_not_overwrite_newer_webhook(reconciliation_env):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    create_pending_order(reconciliation_env["product_id"], transaction, email=email)

    def webhook_arrives(tx: str) -> None:
        deliver("PURCHASE_REFUNDED", tx, email=email, created_at=datetime.now(timezone.utc))

    result = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation("APPROVED"), on_fetch=webhook_arrives),
        dry_run=False,
    )
    assert result.comparison_result == "stale"
    assert result.application_result == "rejected"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        order = db.scalar(select(Order).where(Order.external_order_id == transaction))
        assert order.status == "refunded"


def test_two_reconciliations_share_advisory_lock_and_single_result(reconciliation_env):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    order_id = create_pending_order(reconciliation_env["product_id"], transaction, email=email)
    barrier = threading.Barrier(2)

    def run() -> str:
        return reconcile_transaction(
            transaction,
            run_id=uuid.uuid4(),
            client=FakeClient(observation("APPROVED"), barrier=barrier),
            dry_run=False,
        ).application_result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == ["applied", "rejected"]
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart", payment_order_id=order_id)
        assert db.scalar(select(func.count()).select_from(License).where(License.order_id == order_id)) == 1


@pytest.mark.parametrize("remote_status", ["APPROVED", "CHARGEBACK"])
def test_concurrent_webhook_approval_is_not_overwritten(reconciliation_env, remote_status):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    order_id = create_pending_order(reconciliation_env["product_id"], transaction, email=email)

    def webhook_arrives(tx: str) -> None:
        deliver("PURCHASE_APPROVED", tx, email=email, created_at=datetime.now(timezone.utc))

    result = reconcile_transaction(
        transaction,
        run_id=uuid.uuid4(),
        client=FakeClient(observation(remote_status), on_fetch=webhook_arrives),
        dry_run=False,
    )
    assert result.comparison_result == "stale"
    assert result.application_result == "rejected"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart", payment_order_id=order_id)
        order = db.get(Order, order_id)
        license_row = db.scalar(select(License).where(License.order_id == order_id))
        assert order.status == "paid"
        assert license_row is not None
        assert db.scalar(select(func.count()).select_from(License).where(License.order_id == order_id)) == 1


def test_apply_failure_rolls_back_and_records_error(reconciliation_env, monkeypatch):
    transaction = f"TX-{uuid.uuid4()}"
    email = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    order_id = create_pending_order(reconciliation_env["product_id"], transaction, email=email)

    def fail(*args, **kwargs):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(license_service, "apply_hotmart_approval", fail)
    run_id = uuid.uuid4()
    result = reconcile_transaction(
        transaction,
        run_id=run_id,
        client=FakeClient(observation("APPROVED")),
        dry_run=False,
    )
    assert result.comparison_result == "error"
    assert result.application_result == "failed"
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart", payment_order_id=order_id)
        order = db.get(Order, order_id)
        assert order.status == "pending"
        assert db.scalar(select(func.count()).select_from(License).where(License.order_id == order_id)) == 0
    rows = observations(run_id)
    assert len(rows) == 1 and rows[0].error_code == "RuntimeError"
