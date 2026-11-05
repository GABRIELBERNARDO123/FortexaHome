from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import email_lookup_hash, encrypt_text, masked_email
from app.core.security import hash_password, hash_token, verify_password
from app.models.email_outbox import EmailOutbox
from app.models.password_reset import PasswordResetToken
from app.models.license import License
from app.models.order import Order
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.user import User
from app.integrations.payments.base import PaymentNotification
from app.services import auth_service, license_service
from app.services import email_outbox_service, email_service
from app.workers.email_outbox import check_worker

pytestmark = pytest.mark.integration


@pytest.fixture
def admin_factory(integration_database):
    admin_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    factory = sessionmaker(bind=admin_engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        admin_engine.dispose()


@pytest.fixture(autouse=True)
def isolate_pending_outbox(admin_factory):
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET status = 'cancelled', payload_encrypted = NULL, "
                 "claimed_by = NULL, lease_until = NULL, processed_at = now() "
                 "WHERE status IN ('pending','processing')")
        )
        admin.commit()


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


def enqueue(db, **kwargs) -> EmailOutbox:
    event_type = kwargs.pop("event_type", "password_reset")
    payload = kwargs.pop("payload", {"to": "person@example.test", "token": "private-reset-token"})
    row = email_outbox_service.enqueue_email(
        db,
        event_type=event_type,
        payload=payload,
        idempotency_key=f"test:{uuid.uuid4()}",
        **kwargs,
    )
    return row


def create_paid_license(*, order_status: str = "paid") -> tuple[uuid.UUID, str, uuid.UUID]:
    provider = f"outbox-provider-{uuid.uuid4().hex[:12]}"
    slug = f"outbox-license-{uuid.uuid4().hex[:12]}"
    code = f"FH-OUTBOX-{uuid.uuid4().hex[:12].upper()}"
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=slug,
            name="Produto outbox",
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
            amount_cents=100,
            currency="BRL",
            status=order_status,
        )
        db.add(order)
        db.flush()
        license_row, plain_code = license_service.issue_license(
            db, product, order_id=order.id, code=code
        )
        license_id, order_id = license_row.id, order.id
        db.commit()
        return license_id, plain_code, order_id


def create_reset_account(email: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Reset test", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        db.add(User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(email, "users.email"),
            email_lookup_hash=email_lookup_hash(email),
            email_masked=masked_email(email),
            name_encrypted=encrypt_text("Reset", "users.name"),
            password_hash=hash_password("SenhaSegura#2026"),
            role="owner", status="active", theme="claro",
        ))
        db.commit()
    return tenant_id


def test_worker_role_is_restricted_and_has_no_rls_bypass(worker_factory, admin_factory):
    with worker_factory() as worker:
        check_worker(worker_factory)
        role = worker.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb, r.rolinherit "
                 "FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
        assert role == (os.environ["OUTBOX_DB_USER"], False, False, False, False, False)
        with pytest.raises(DBAPIError):
            worker.execute(text(f"SET ROLE {os.environ['APP_DB_USER']}"))
        worker.rollback()
        with pytest.raises(DBAPIError):
            worker.execute(text("SELECT id FROM users LIMIT 1")).all()
        worker.rollback()
        for protected in ("payment_events", "products"):
            with pytest.raises(DBAPIError):
                worker.execute(text(f"SELECT id FROM {protected} LIMIT 1")).all()
            worker.rollback()
        assert worker.execute(text("SELECT id FROM licenses LIMIT 1")).all() == []
        worker.rollback()
        assert worker.execute(text("SELECT id FROM orders LIMIT 1")).all() == []
        worker.rollback()
        with pytest.raises(DBAPIError):
            worker.execute(text("SELECT code_hash FROM licenses LIMIT 1")).all()
        worker.rollback()
        with pytest.raises(DBAPIError):
            worker.execute(text("SELECT buyer_email_encrypted FROM orders LIMIT 1")).all()
        worker.rollback()
        license_id, _, order_id = create_paid_license()
        worker.execute(text("SELECT set_config('app.outbox_license_id', :id, true)"), {"id": str(license_id)})
        assert worker.execute(
            text("SELECT status, order_id FROM licenses WHERE id = :id"), {"id": license_id}
        ).one() == ("pending", order_id)
        worker.rollback()
        worker.execute(text("SELECT set_config('app.outbox_order_id', :id, true)"), {"id": str(order_id)})
        assert worker.execute(
            text("SELECT status FROM orders WHERE id = :id"), {"id": order_id}
        ).scalar_one() == "paid"
        worker.rollback()

    with SessionLocal() as app:
        with pytest.raises(DBAPIError):
            app.execute(text("SELECT payload_encrypted FROM email_outbox")).all()
        app.rollback()
        row = enqueue(app, event_type="activation_verification", payload={"to": "app@example.test", "code": "123456"})
        app.commit()
        row_id = row.id
        result = app.execute(
            text("UPDATE email_outbox SET status = 'sent' WHERE id = :id"), {"id": row_id}
        )
        assert result.rowcount == 0
        app.commit()
    with admin_factory() as admin:
        assert admin.get(EmailOutbox, row_id).status == "pending"


def test_license_delivery_and_reset_emails_are_enqueued_in_business_transactions(monkeypatch, admin_factory):
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args))
    slug = f"outbox-product-{uuid.uuid4().hex[:12]}"
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        db.add(Product(slug=slug, name="Produto teste", price_cents=100, currency="BRL", license_kind="lifetime", active=True))
        db.commit()

    notification = PaymentNotification(
        event_id=f"event-{uuid.uuid4()}",
        event_type="payment.paid",
        external_order_id=f"order-{uuid.uuid4()}",
        product_slug=slug,
        buyer_email=f"buyer-{uuid.uuid4().hex[:8]}@example.test",
        amount_cents=100,
        currency="BRL",
    )
    with SessionLocal() as db:
        result = license_service.process_payment_notification(
            db, notification, provider="sandbox-test", payload_hash="a" * 64
        )
    assert result["status"] == "processed"
    assert not delivered
    with admin_factory() as admin:
        license_event = admin.scalar(
            select(EmailOutbox).where(
                EmailOutbox.event_type == "license_delivery",
                EmailOutbox.idempotency_key.like("license-delivery:%"),
            ).order_by(EmailOutbox.created_at.desc())
        )
        assert license_event is not None
        assert notification.buyer_email not in license_event.payload_encrypted
        assert result["license_code"] not in license_event.payload_encrypted

    tenant_id = uuid.uuid4()
    email = f"reset-{uuid.uuid4().hex[:8]}@example.test"
    email_hash = email_lookup_hash(email)
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Outbox reset", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        db.add(
            User(
                tenant_id=tenant_id,
                email_encrypted=encrypt_text(email, "users.email"),
                email_lookup_hash=email_hash,
                email_masked=masked_email(email),
                name_encrypted=encrypt_text("Reset", "users.name"),
                password_hash=hash_password("SenhaSegura#2026"),
                role="owner",
                status="active",
                theme="claro",
            )
        )
        db.commit()
    with SessionLocal() as db:
        token = auth_service.forgot_password(db, email=email)
    assert token
    assert not delivered
    with admin_factory() as admin:
        reset_event = admin.scalar(
            select(EmailOutbox).where(
                EmailOutbox.event_type == "password_reset",
                EmailOutbox.idempotency_key.like("password-reset:%"),
            ).order_by(EmailOutbox.created_at.desc())
        )
        assert reset_event is not None
        assert email not in reset_event.payload_encrypted
        assert token not in reset_event.payload_encrypted


def test_new_reset_request_invalidates_previous_token_and_cancels_old_email(admin_factory):
    email = f"reset-replace-{uuid.uuid4().hex[:8]}@example.test"
    create_reset_account(email)
    with SessionLocal() as db:
        old_token = auth_service.forgot_password(db, email=email)
    with admin_factory() as admin:
        old_row = admin.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(old_token)))
        old_id = old_row.id
        old_event = admin.scalar(select(EmailOutbox).where(EmailOutbox.aggregate_id == old_id))
        old_event_id = old_event.id

    with SessionLocal() as db:
        new_token = auth_service.forgot_password(db, email=email)
    assert new_token and new_token != old_token
    with admin_factory() as admin:
        old_row = admin.get(PasswordResetToken, old_id)
        old_event = admin.get(EmailOutbox, old_event_id)
        new_row = admin.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(new_token)))
        assert old_row.used_at is not None
        assert old_event.status == "cancelled"
        assert old_event.payload_encrypted is None
        assert new_row.used_at is None
        new_event = admin.scalar(select(EmailOutbox).where(EmailOutbox.aggregate_id == new_row.id))
        assert new_event.status == "pending"
    with SessionLocal() as db:
        with pytest.raises(HTTPException):
            auth_service.reset_password(db, token=old_token, new_password="SenhaQueNaoDeveSerAceita#2026")


def test_password_reset_consumes_token_and_cancels_queued_message(admin_factory):
    email = f"reset-complete-{uuid.uuid4().hex[:8]}@example.test"
    create_reset_account(email)
    with SessionLocal() as db:
        token = auth_service.forgot_password(db, email=email)
    with admin_factory() as admin:
        token_row = admin.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
        token_id = token_row.id
        event_id = admin.scalar(select(EmailOutbox.id).where(EmailOutbox.aggregate_id == token_id))
    with SessionLocal() as db:
        auth_service.reset_password(db, token=token, new_password="NovaSenha#2026")
    with admin_factory() as admin:
        token_row = admin.get(PasswordResetToken, token_id)
        event = admin.get(EmailOutbox, event_id)
        assert token_row.used_at is not None
        assert event.status == "cancelled"
        assert event.payload_encrypted is None
        updated_user = admin.get(User, token_row.user_id)
        assert verify_password("NovaSenha#2026", updated_user.password_hash)
    with SessionLocal() as db:
        with pytest.raises(HTTPException):
            auth_service.reset_password(db, token=token, new_password="OutraSenha#2026")


def test_worker_discards_currently_used_reset_token(admin_factory, worker_factory, monkeypatch):
    email = f"reset-used-{uuid.uuid4().hex[:8]}@example.test"
    create_reset_account(email)
    with SessionLocal() as db:
        token = auth_service.forgot_password(db, email=email)
    with admin_factory() as admin:
        token_row = admin.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
        worker_id = uuid.uuid4()
        row_id = admin.scalar(select(EmailOutbox.id).where(EmailOutbox.aggregate_id == token_row.id))
        admin.execute(
            text("UPDATE email_outbox SET status='processing', claimed_by=:worker, lease_until=now()+interval '1 minute' WHERE id=:id"),
            {"worker": worker_id, "id": row_id},
        )
        admin.commit()
        admin.execute(text("UPDATE password_reset_tokens SET used_at=now() WHERE id=:id"), {"id": token_row.id})
        admin.commit()
    sent = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: sent.append(args))
    with worker_factory() as worker:
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "cancelled"
    assert sent == []
    with admin_factory() as admin:
        event = admin.get(EmailOutbox, row_id)
        assert event.status == "cancelled"
        assert event.payload_encrypted is None
        assert event.last_error == "obsolete_reset_token"


def test_expired_password_reset_message_is_cancelled_before_provider_call(admin_factory, worker_factory, monkeypatch):
    email = f"reset-expiry-{uuid.uuid4().hex[:8]}@example.test"
    create_reset_account(email)
    with SessionLocal() as db:
        token = auth_service.forgot_password(db, email=email)
    with admin_factory() as admin:
        token_row = admin.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
        event = admin.scalar(select(EmailOutbox).where(EmailOutbox.aggregate_id == token_row.id))
        admin.execute(
            text("UPDATE password_reset_tokens SET expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": token_row.id},
        )
        admin.execute(
            text("UPDATE email_outbox SET expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": event.id},
        )
        event_id = event.id
        admin.commit()
    sent = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: sent.append(args))
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, uuid.uuid4()) == []
    assert sent == []
    with admin_factory() as admin:
        event = admin.get(EmailOutbox, event_id)
        assert event.status == "cancelled"
        assert event.payload_encrypted is None
        assert event.last_error == "expired"


def test_worker_reset_status_access_is_column_and_token_scoped(admin_factory, worker_factory):
    email = f"reset-scope-{uuid.uuid4().hex[:8]}@example.test"
    create_reset_account(email)
    with SessionLocal() as app:
        token = auth_service.forgot_password(app, email=email)
    with admin_factory() as admin:
        token_row = admin.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
        token_id = token_row.id
    with worker_factory() as worker:
        worker.execute(text("SELECT set_config('app.outbox_reset_token_id', :id, true)"), {"id": str(token_id)})
        assert worker.execute(text("SELECT used_at, expires_at FROM password_reset_tokens WHERE id=:id"), {"id": token_id}).one()
        worker.rollback()
        with pytest.raises(DBAPIError):
            worker.execute(text("SELECT token_hash FROM password_reset_tokens WHERE id=:id"), {"id": token_id}).all()
        worker.rollback()


def test_dead_recovery_rejects_obsolete_reset_and_activation_messages(admin_factory, worker_factory):
    email = f"reset-requeue-{uuid.uuid4().hex[:8]}@example.test"
    create_reset_account(email)
    with SessionLocal() as db:
        token = auth_service.forgot_password(db, email=email)
    with admin_factory() as admin:
        reset_row = admin.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
        reset_event = admin.scalar(select(EmailOutbox).where(EmailOutbox.aggregate_id == reset_row.id))
        reset_event.status = "dead"
        reset_row.used_at = datetime.now(timezone.utc)
        activation_event = enqueue(
            admin,
            event_type="activation_verification",
            payload={"to": email, "code": "123456"},
            aggregate_id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        activation_event.status = "dead"
        expired_event = enqueue(
            admin,
            event_type="license_delivery",
            payload={"to": email, "code": "FH-EXPIRED", "product_name": "Produto"},
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        expired_event.status = "dead"
        admin.commit()
        reset_event_id, activation_event_id, expired_event_id = reset_event.id, activation_event.id, expired_event.id
    with worker_factory() as worker:
        assert not email_outbox_service.requeue_dead(worker, reset_event_id)
        assert not email_outbox_service.requeue_dead(worker, activation_event_id)
        assert not email_outbox_service.requeue_dead(worker, expired_event_id)
    with admin_factory() as admin:
        assert admin.get(EmailOutbox, reset_event_id).status == "dead"
        assert admin.get(EmailOutbox, activation_event_id).status == "dead"
        assert admin.get(EmailOutbox, expired_event_id).status == "dead"


def test_queue_snapshot_exposes_aggregate_health_without_payload(worker_factory, admin_factory):
    with SessionLocal() as app:
        pending = enqueue(app, event_type="license_delivery", payload={"to": "hidden@example.test", "code": "secret", "product_name": "Product"})
        processing = enqueue(app, event_type="license_delivery", payload={"to": "hidden@example.test", "code": "secret", "product_name": "Product"})
        dead = enqueue(app, event_type="license_delivery", payload={"to": "hidden@example.test", "code": "secret", "product_name": "Product"})
        ids = pending.id, processing.id, dead.id
        app.commit()
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET status='processing', claimed_by=:worker, lease_until=now()-interval '1 minute' WHERE id=:id"),
            {"worker": uuid.uuid4(), "id": ids[1]},
        )
        admin.execute(
            text("UPDATE email_outbox SET status='dead', last_error='provider_unavailable', processed_at=now() WHERE id=:id"),
            {"id": ids[2]},
        )
        admin.commit()
    with worker_factory() as worker:
        snapshot = email_outbox_service.queue_snapshot(worker)
    assert snapshot["pending"] >= 1
    assert snapshot["processing"] >= 1
    assert snapshot["expired_leases"] >= 1
    assert snapshot["dead"] >= 1
    assert snapshot["provider_errors_15m"] >= 1
    assert snapshot["oldest_pending_seconds"] is not None


def test_worker_heartbeat_healthcheck_detects_missing_and_stale_loop(tmp_path, monkeypatch):
    from app.workers import email_outbox as worker_module

    heartbeat = tmp_path / "worker-heartbeat"
    monkeypatch.setattr(worker_module, "_HEARTBEAT", heartbeat)
    with pytest.raises(RuntimeError, match="heartbeat"):
        worker_module.check_heartbeat()
    worker_module.write_heartbeat()
    worker_module.check_heartbeat()
    heartbeat.write_text("0", encoding="ascii")
    with pytest.raises(RuntimeError, match="sem heartbeat"):
        worker_module.check_heartbeat()


def test_payload_is_encrypted_in_postgres_and_sent_payload_is_scrubbed(worker_factory, admin_factory, monkeypatch):
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda to, subject, body, **kw: delivered.append((to, body, kw)) or "mail-id")
    license_id, license_code, _ = create_paid_license()
    with SessionLocal() as app:
        row = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "person@example.test", "code": license_code, "product_name": "Produto"},
            aggregate_id=license_id,
        )
        row_id = row.id
        app.commit()

    with admin_factory() as admin:
        ciphertext = admin.scalar(select(EmailOutbox.payload_encrypted).where(EmailOutbox.id == row_id))
        assert ciphertext is not None
        assert "private-reset-token" not in ciphertext
        assert "person@example.test" not in ciphertext

    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        ids = email_outbox_service.claim_batch(worker, worker_id)
        assert ids == [row_id]
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "sent"
    assert len(delivered) == 1
    assert license_code in delivered[0][1]
    assert delivered[0][2]["idempotency_key"]
    with admin_factory() as admin:
        sent = admin.get(EmailOutbox, row_id)
        assert sent.status == "sent"
        assert sent.payload_encrypted is None
        assert sent.provider_message_id == "mail-id"


def test_resend_adapter_uses_stable_idempotency_key_and_classifies_failures(monkeypatch):
    import httpx

    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(email_service.settings, "RESEND_API_KEY", "test-resend-key")
    monkeypatch.setattr(email_service.settings, "EMAIL_FROM", "Fortexa <mail@example.test>")
    captured = {}
    def accepted(url, *, headers, json, timeout):
        captured.update(headers=headers, body=json, timeout=timeout)
        return httpx.Response(200, json={"id": "resend-id"})
    monkeypatch.setattr(email_service.httpx, "post", accepted)
    assert email_service.send_rendered_email(
        "person@example.test", "Subject", "Body", idempotency_key="stable-event-key"
    ) == "resend-id"
    assert captured["headers"]["Idempotency-Key"] == "stable-event-key"

    monkeypatch.setattr(email_service.httpx, "post", lambda *_args, **_kwargs: httpx.Response(503))
    with pytest.raises(email_service.TransientEmailDeliveryError):
        email_service.send_rendered_email("person@example.test", "Subject", "Body", idempotency_key="stable-event-key")
    monkeypatch.setattr(email_service.httpx, "post", lambda *_args, **_kwargs: httpx.Response(400))
    with pytest.raises(email_service.PermanentEmailDeliveryError):
        email_service.send_rendered_email("person@example.test", "Subject", "Body", idempotency_key="stable-event-key")
    monkeypatch.setattr(
        email_service.httpx,
        "post",
        lambda *_args, **_kwargs: httpx.Response(409, json={"name": "concurrent_idempotent_requests"}),
    )
    with pytest.raises(email_service.TransientEmailDeliveryError):
        email_service.send_rendered_email("person@example.test", "Subject", "Body", idempotency_key="stable-event-key")
    monkeypatch.setattr(
        email_service.httpx,
        "post",
        lambda *_args, **_kwargs: httpx.Response(409, json={"name": "invalid_idempotent_request"}),
    )
    with pytest.raises(email_service.PermanentEmailDeliveryError):
        email_service.send_rendered_email("person@example.test", "Subject", "Body", idempotency_key="stable-event-key")
    monkeypatch.setattr(
        email_service.httpx,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("timeout")),
    )
    with pytest.raises(email_service.TransientEmailDeliveryError):
        email_service.send_rendered_email("person@example.test", "Subject", "Body", idempotency_key="stable-event-key")


def test_exponential_backoff_is_jittered_and_capped(monkeypatch):
    monkeypatch.setattr(email_outbox_service.settings, "OUTBOX_RETRY_BASE_SECONDS", 5.0)
    monkeypatch.setattr(email_outbox_service.settings, "OUTBOX_RETRY_MAX_SECONDS", 20.0)
    monkeypatch.setattr(email_outbox_service.random, "uniform", lambda low, high: high)
    assert email_outbox_service._backoff_seconds(1) == 5.0
    assert email_outbox_service._backoff_seconds(2) == 10.0
    assert email_outbox_service._backoff_seconds(8) == 20.0


def test_worker_retries_transient_failure_then_marks_dead_at_limit(worker_factory, admin_factory, monkeypatch):
    license_id, license_code, _ = create_paid_license()
    with SessionLocal() as app:
        row = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "person@example.test", "code": license_code, "product_name": "Produto"},
            aggregate_id=license_id,
        )
        row_id = row.id
        app.commit()
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET max_attempts = 2, next_attempt_at = now() WHERE id = :id"),
            {"id": row_id},
        )
        admin.commit()

    monkeypatch.setattr(email_outbox_service, "_backoff_seconds", lambda _attempt: 12)
    monkeypatch.setattr(
        email_service,
        "send_rendered_email",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(email_service.TransientEmailDeliveryError("provider_unavailable")),
    )
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        first = email_outbox_service.claim_batch(worker, worker_id)
        assert first == [row_id]
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "pending"
    with admin_factory() as admin:
        pending = admin.get(EmailOutbox, row_id)
        assert pending.attempt_count == 1
        assert pending.status == "pending"
        assert pending.last_error == "provider_unavailable"
        assert pending.payload_encrypted is not None
        assert pending.next_attempt_at >= datetime.now(timezone.utc) + timedelta(seconds=10)
        admin.execute(text("UPDATE email_outbox SET next_attempt_at = now() - interval '1 second' WHERE id = :id"), {"id": row_id})
        admin.commit()
    with worker_factory() as worker:
        second = email_outbox_service.claim_batch(worker, worker_id)
        assert second == [row_id]
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "dead"
    with admin_factory() as admin:
        dead = admin.get(EmailOutbox, row_id)
        assert dead.status == "dead"
        assert dead.attempt_count == 2
        assert dead.payload_encrypted is not None
        assert dead.last_error == "provider_unavailable"
    original_max_attempts = dead.max_attempts
    original_idempotency_key = dead.idempotency_key
    with worker_factory() as worker:
        assert email_outbox_service.requeue_dead(worker, row_id)
    with admin_factory() as admin:
        recovered = admin.get(EmailOutbox, row_id)
        assert recovered.status == "pending"
        assert recovered.attempt_count == 2
        assert recovered.max_attempts == original_max_attempts + email_outbox_service.settings.OUTBOX_MAX_ATTEMPTS
        assert recovered.manual_requeue_count == 1
        assert recovered.idempotency_key == original_idempotency_key
        assert recovered.last_requeued_at is not None
        assert recovered.last_requeued_by == os.environ["OUTBOX_DB_USER"]
        assert recovered.payload_encrypted is not None
    with worker_factory() as worker:
        assert not email_outbox_service.requeue_dead(worker, row_id)


def test_dead_payload_is_scrubbed_after_retention(worker_factory, admin_factory, monkeypatch):
    monkeypatch.setattr(email_outbox_service.settings, "OUTBOX_DEAD_PAYLOAD_RETENTION_DAYS", 1)
    with SessionLocal() as app:
        row = enqueue(app)
        row_id = row.id
        app.commit()
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET status = 'dead', processed_at = now() - interval '2 days' WHERE id = :id"),
            {"id": row_id},
        )
        admin.commit()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, uuid.uuid4()) == []
    with admin_factory() as admin:
        expired = admin.get(EmailOutbox, row_id)
        assert expired.status == "dead"
        assert expired.payload_encrypted is None


def test_expired_lease_is_reclaimed_and_concurrent_workers_claim_distinct_rows(worker_factory, admin_factory):
    with SessionLocal() as app:
        first = enqueue(app)
        second = enqueue(app)
        first_id, second_id = first.id, second.id
        app.commit()
    with admin_factory() as admin:
        admin.execute(text("UPDATE email_outbox SET next_attempt_at = now() WHERE id IN (:a, :b)"), {"a": first_id, "b": second_id})
        admin.commit()

    abandoned_worker = uuid.uuid4()
    with worker_factory() as worker:
        claimed = email_outbox_service.claim_batch(worker, abandoned_worker, batch_size=1)
        assert len(claimed) == 1
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET lease_until = now() - interval '1 second' WHERE id = :id"),
            {"id": claimed[0]},
        )
        admin.commit()

    worker_a, worker_b = uuid.uuid4(), uuid.uuid4()
    def take(worker_id):
        with worker_factory() as worker:
            return email_outbox_service.claim_batch(worker, worker_id, batch_size=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(take, [worker_a, worker_b]))
    claimed_ids = [result[0] for result in results if result]
    assert len(claimed_ids) == 2
    assert len(set(claimed_ids)) == 2
    assert set(claimed_ids) == {first_id, second_id}
    with admin_factory() as admin:
        rows = admin.scalars(select(EmailOutbox).where(EmailOutbox.id.in_(claimed_ids))).all()
        assert sorted(row.attempt_count for row in rows) == [1, 2]


def test_activation_event_expiration_is_cancelled_before_provider_call(worker_factory, admin_factory, monkeypatch):
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args) or "ok")
    with SessionLocal() as app:
        row = email_outbox_service.enqueue_email(
            app,
            event_type="activation_verification",
            payload={"to": "person@example.test", "code": "123456"},
            idempotency_key=f"expired:{uuid.uuid4()}",
            aggregate_id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        row_id = row.id
        app.commit()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, uuid.uuid4()) == []
    assert not delivered
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "cancelled"
        assert row.payload_encrypted is None


def test_two_workers_skip_locked_claims_are_disjoint(worker_factory, admin_factory):
    with SessionLocal() as app:
        first = enqueue(app)
        second = enqueue(app)
        app.commit()
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET next_attempt_at = now() WHERE id IN (:a, :b)"),
            {"a": first.id, "b": second.id},
        )
        admin.commit()
    worker_ids = [uuid.uuid4(), uuid.uuid4()]
    def claim(worker_id):
        with worker_factory() as worker:
            return email_outbox_service.claim_batch(worker, worker_id, batch_size=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(claim, worker_ids))
    flattened = [row_id for batch in batches for row_id in batch]
    assert set(flattened) == {first.id, second.id}
    assert len(flattened) == len(set(flattened))


def test_cancel_license_delivery_is_scoped_and_clears_payload(admin_factory):
    first_license, first_code, _ = create_paid_license()
    second_license, second_code, _ = create_paid_license()
    with SessionLocal() as app:
        first = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "first@example.test", "code": first_code, "product_name": "Produto"},
            aggregate_id=first_license,
        )
        second = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "second@example.test", "code": second_code, "product_name": "Produto"},
            aggregate_id=second_license,
        )
        reset = enqueue(
            app,
            event_type="password_reset",
            payload={"to": "reset@example.test", "token": "reset-token"},
            aggregate_id=uuid.uuid4(),
        )
        app.commit()
        first_id, second_id, reset_id = first.id, second.id, reset.id
        email_outbox_service.cancel_license_delivery(app, first_license, reason="license_revoked")
        app.commit()

    with admin_factory() as admin:
        first_row = admin.get(EmailOutbox, first_id)
        second_row = admin.get(EmailOutbox, second_id)
        reset_row = admin.get(EmailOutbox, reset_id)
        assert first_row.status == "cancelled"
        assert first_row.payload_encrypted is None
        assert first_row.last_error == "license_revoked"
        assert second_row.status == "pending"
        assert second_row.payload_encrypted is not None
        assert reset_row.status == "pending"
        assert reset_row.payload_encrypted is not None


def test_cancel_license_delivery_does_not_alter_sent_message(admin_factory):
    license_id, code, _ = create_paid_license()
    with SessionLocal() as app:
        row = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "sent@example.test", "code": code, "product_name": "Produto"},
            aggregate_id=license_id,
        )
        app.commit()
        row_id = row.id
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET status='sent', sent_at=now(), processed_at=now() WHERE id=:id"),
            {"id": row_id},
        )
        admin.commit()
    with SessionLocal() as app:
        email_outbox_service.cancel_license_delivery(app, license_id, reason="license_revoked")
        app.commit()
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "sent"
        assert row.payload_encrypted is not None


def test_worker_cancels_delivery_when_order_is_not_paid(worker_factory, admin_factory, monkeypatch):
    license_id, code, _ = create_paid_license(order_status="refunded")
    with SessionLocal() as app:
        row = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "refunded@example.test", "code": code, "product_name": "Produto"},
            aggregate_id=license_id,
        )
        app.commit()
        row_id = row.id
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args))
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert row_id in email_outbox_service.claim_batch(worker, worker_id)
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "cancelled"
    assert delivered == []
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "cancelled"
        assert row.payload_encrypted is None
        assert row.last_error == "license_not_deliverable"


def test_worker_cancels_delivery_when_license_is_missing(worker_factory, admin_factory, monkeypatch):
    with SessionLocal() as app:
        row = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "missing@example.test", "code": "FH-MISSING", "product_name": "Produto"},
            aggregate_id=uuid.uuid4(),
        )
        app.commit()
        row_id = row.id
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args))
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert row_id in email_outbox_service.claim_batch(worker, worker_id)
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "cancelled"
    assert delivered == []
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "cancelled"
        assert row.last_error == "license_not_deliverable"


def test_worker_defers_delivery_while_order_is_pending(worker_factory, admin_factory, monkeypatch):
    license_id, code, _ = create_paid_license(order_status="pending")
    with SessionLocal() as app:
        row = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "pending@example.test", "code": code, "product_name": "Produto"},
            aggregate_id=license_id,
        )
        app.commit()
        row_id = row.id
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args))
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert row_id in email_outbox_service.claim_batch(worker, worker_id)
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "pending"
    assert delivered == []
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "pending"
        assert row.attempt_count == 0
        assert row.payload_encrypted is not None
        assert row.last_error == "license_pending"
        assert row.next_attempt_at > datetime.now(timezone.utc)


def test_dead_license_delivery_for_refunded_order_cannot_be_requeued(admin_factory, worker_factory):
    license_id, code, _ = create_paid_license(order_status="refunded")
    with SessionLocal() as app:
        row = enqueue(
            app,
            event_type="license_delivery",
            payload={"to": "dead-refund@example.test", "code": code, "product_name": "Produto"},
            aggregate_id=license_id,
        )
        app.commit()
        row_id = row.id
    with admin_factory() as admin:
        admin.execute(text("UPDATE email_outbox SET status='dead' WHERE id=:id"), {"id": row_id})
        admin.commit()
    with worker_factory() as worker:
        assert not email_outbox_service.requeue_dead(worker, row_id)
    with admin_factory() as admin:
        assert admin.get(EmailOutbox, row_id).status == "dead"


def _activation_event(app, *, aggregate_id: uuid.UUID | None = None, expires_at=None) -> EmailOutbox:
    return enqueue(
        app,
        event_type="activation_verification",
        payload={"to": "activation@example.test", "code": "123456"},
        aggregate_id=aggregate_id or uuid.uuid4(),
        expires_at=expires_at,
    )


def test_generic_activation_cancelled_before_processing_is_not_sent(worker_factory, admin_factory, monkeypatch):
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args) or "ok")
    activation_id = uuid.uuid4()
    with SessionLocal() as app:
        row = _activation_event(app, aggregate_id=activation_id)
        row_id = row.id
        app.commit()
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, worker_id) == [row_id]
    with SessionLocal() as app:
        set_db_context(app, pending_activation_id=activation_id)
        email_outbox_service.cancel_activation_emails(app, activation_id)
        app.commit()
    with worker_factory() as worker:
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "cancelled"
    assert delivered == []
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "cancelled"
        assert row.payload_encrypted is None


def test_generic_activation_substituted_is_not_sent(worker_factory, admin_factory, monkeypatch):
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args) or "ok")
    activation_id = uuid.uuid4()
    with SessionLocal() as app:
        old = _activation_event(app, aggregate_id=activation_id)
        old_id = old.id
        app.commit()
    old_worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, old_worker_id) == [old_id]
    with SessionLocal() as app:
        set_db_context(app, pending_activation_id=activation_id)
        email_outbox_service.cancel_activation_emails(app, activation_id)
        new = _activation_event(app, aggregate_id=activation_id)
        new_id = new.id
        app.commit()
    with worker_factory() as worker:
        assert email_outbox_service.process_one(worker, old_id, old_worker_id) == "cancelled"
    assert delivered == []
    with admin_factory() as admin:
        assert admin.get(EmailOutbox, old_id).status == "cancelled"
        assert admin.get(EmailOutbox, old_id).payload_encrypted is None
        assert admin.get(EmailOutbox, new_id).payload_encrypted is not None


def test_generic_processing_expired_activation_is_cancelled(worker_factory, admin_factory, monkeypatch):
    delivered = []
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *args, **kwargs: delivered.append(args) or "ok")
    with SessionLocal() as app:
        row = _activation_event(app)
        row_id = row.id
        app.commit()
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, worker_id) == [row_id]
    with admin_factory() as admin:
        admin.execute(
            text("UPDATE email_outbox SET expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": row_id},
        )
        admin.commit()
    with worker_factory() as worker:
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "cancelled"
    assert delivered == []
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "cancelled"
        assert row.payload_encrypted is None
        assert row.last_error == "expired"


def test_generic_worker_holds_lock_while_cancellation_waits(worker_factory, admin_factory, monkeypatch):
    started = Event()
    release = Event()
    cancelled = Event()

    def slow_send(*_args, **_kwargs):
        started.set()
        assert release.wait(5)
        return "mail-id"

    monkeypatch.setattr(email_service, "send_rendered_email", slow_send)
    activation_id = uuid.uuid4()
    with SessionLocal() as app:
        row = _activation_event(app, aggregate_id=activation_id)
        row_id = row.id
        app.commit()
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, worker_id) == [row_id]

    result: dict[str, str] = {}

    def run_worker():
        with worker_factory() as worker:
            result["status"] = email_outbox_service.process_one(worker, row_id, worker_id)

    def run_cancel():
        with SessionLocal() as app:
            set_db_context(app, pending_activation_id=activation_id)
            email_outbox_service.cancel_activation_emails(app, activation_id)
            app.commit()
        cancelled.set()

    worker_thread = Thread(target=run_worker)
    worker_thread.start()
    assert started.wait(5)
    cancel_thread = Thread(target=run_cancel)
    cancel_thread.start()
    # The cancellation transaction must wait for the outbox row lock held by
    # the worker during provider I/O.
    assert not cancelled.wait(0.5)
    release.set()
    worker_thread.join(5)
    cancel_thread.join(5)
    assert result["status"] == "sent"
    assert cancelled.is_set()
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "sent"
        assert row.payload_encrypted is None


def test_generic_transient_failure_releases_lock_and_keeps_encrypted_payload(worker_factory, admin_factory, monkeypatch):
    monkeypatch.setattr(email_outbox_service, "_backoff_seconds", lambda _attempt: 12)
    monkeypatch.setattr(
        email_service,
        "send_rendered_email",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(email_service.TransientEmailDeliveryError("provider_unavailable")),
    )
    with SessionLocal() as app:
        row = _activation_event(app)
        row_id = row.id
        app.commit()
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, worker_id) == [row_id]
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "pending"
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "pending"
        assert row.payload_encrypted is not None
        assert row.last_error == "provider_unavailable"
        assert row.next_attempt_at >= datetime.now(timezone.utc)
        # Lock was released: an administrative update can proceed.
        admin.execute(text("UPDATE email_outbox SET last_error='lock_released' WHERE id=:id"), {"id": row_id})
        admin.commit()


def test_generic_permanent_failure_marks_dead(worker_factory, admin_factory, monkeypatch):
    monkeypatch.setattr(
        email_service,
        "send_rendered_email",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(email_service.PermanentEmailDeliveryError("provider_rejected")),
    )
    with SessionLocal() as app:
        row = _activation_event(app)
        row_id = row.id
        app.commit()
    worker_id = uuid.uuid4()
    with worker_factory() as worker:
        assert email_outbox_service.claim_batch(worker, worker_id) == [row_id]
        assert email_outbox_service.process_one(worker, row_id, worker_id) == "dead"
    with admin_factory() as admin:
        row = admin.get(EmailOutbox, row_id)
        assert row.status == "dead"
        assert row.payload_encrypted is not None
        assert row.last_error == "permanent_failure"
