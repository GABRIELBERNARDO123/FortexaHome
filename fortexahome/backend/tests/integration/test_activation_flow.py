from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, local

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal, engine, set_db_context
from app.core.field_encryption import decrypt_text, email_lookup_hash, license_code_hash
from app.core.rate_limit import limiter
from app.models.license import License
from app.models.audit_log import AuditLog
from app.models.category import Category
from app.models.order import Order
from app.models.pending_activation import PendingActivation
from app.models.email_outbox import EmailOutbox
from app.models.session import UserSession
from app.models.tenant import Tenant
from app.models.user import User
from app.services import activation_service
from app.services import email_outbox_service, email_service
from app.services.license_service import issue_license
from app.models.product import Product
from app import main

pytestmark = pytest.mark.integration


@pytest.fixture
def email_sink(monkeypatch):
    class Sink(list):
        enqueue = None

    sent = Sink()
    original = email_outbox_service.enqueue_email

    def enqueue(db, *, event_type, payload, **kwargs):
        if event_type == "activation_verification":
            sent.append((payload["to"], payload["code"]))
        return original(db, event_type=event_type, payload=payload, **kwargs)

    sent.enqueue = enqueue
    monkeypatch.setattr(activation_service.email_outbox_service, "enqueue_email", enqueue)
    return sent


@pytest.fixture
def admin_sessions(integration_database):
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def seed_license(code: str | None = None, buyer_email: str | None = None) -> tuple[str, uuid.UUID]:
    code = code or f"FH-ACT-{uuid.uuid4().hex[:18]}"
    db = SessionLocal()
    try:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=f"activation-{uuid.uuid4().hex[:14]}",
            name="Activation integration",
            price_cents=1,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.flush()
        row, _ = issue_license(db, product, code=code, buyer_email=buyer_email)
        license_id = row.id
        db.commit()
        return code, license_id
    finally:
        db.close()


def seed_ordered_license() -> tuple[str, uuid.UUID, uuid.UUID, str]:
    code = f"FH-ORD-{uuid.uuid4().hex[:18]}"
    provider = f"test-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=f"ordered-activation-{uuid.uuid4().hex[:12]}",
            name="Ordered activation integration",
            price_cents=1,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.flush()
        set_db_context(db, payment_provider=provider)
        order = Order(
            provider=provider,
            external_order_id=str(uuid.uuid4()),
            product_id=product.id,
            amount_cents=1,
            currency="BRL",
            status="paid",
        )
        db.add(order)
        db.flush()
        license_row, _ = issue_license(db, product, order_id=order.id, code=code)
        license_id, order_id = license_row.id, order.id
        db.commit()
        return code, license_id, order_id, provider
    finally:
        db.close()


def start(db: Session, code: str, email: str | None = None, password: str = "SenhaSegura#2026") -> dict:
    return activation_service.start_activation(
        db,
        name="Pessoa de Teste",
        email=email or f"{uuid.uuid4().hex[:12]}@example.test",
        password=password,
        license_code=code,
    )


def test_api_activation_has_no_account_or_session_until_confirmation(monkeypatch, email_sink, admin_sessions, caplog):
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(email_service, "send_rendered_email", lambda *_args, **_kwargs: pytest.fail("HTTP path sent mail directly"))
    email = f"flow-{uuid.uuid4().hex[:10]}@example.com"
    code, license_id = seed_license()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/auth/activate",
            json={"name": "Pessoa Teste", "email": email, "password": "SenhaSegura#2026", "license_code": code},
        )
        assert response.status_code == 202, response.text
        challenge = response.json()
        assert "code" not in response.text
        assert "verification_code" not in response.text
        assert "set-cookie" not in response.headers
        assert len(email_sink) == 1
        assert email_sink[0][1] not in caplog.text
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "SenhaSegura#2026"}).status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 401

        with admin_sessions() as admin:
            assert admin.scalar(select(User).where(User.email_lookup_hash == email_lookup_hash(email))) is None
            assert admin.scalar(
                select(UserSession).join(User).where(User.email_lookup_hash == email_lookup_hash(email))
            ) is None
            activation = admin.get(PendingActivation, challenge["activation_id"])
            assert activation is not None
            assert activation.password_hash != "SenhaSegura#2026"
            assert activation.verification_code_hash != email_sink[0][1]
            assert activation.email_encrypted != email
            assert admin.get(License, license_id).tenant_id is None
            activation_mail = admin.scalar(
                select(EmailOutbox).where(EmailOutbox.aggregate_id == activation.id)
            )
            assert activation_mail.status == "pending"
            assert activation_mail.payload_encrypted is not None

        confirmed = client.post(
            "/api/v1/auth/activate/confirm",
            json={"activation_id": challenge["activation_id"], "code": email_sink[0][1]},
        )
        assert confirmed.status_code == 201, confirmed.text
        assert "fh_session=" in confirmed.headers.get("set-cookie", "")
        assert client.get("/api/v1/auth/me").status_code == 200
        with admin_sessions() as admin:
            user = admin.scalar(select(User).where(User.email_lookup_hash == email_lookup_hash(email)))
            assert user.email_verified_at is not None
            assert admin.scalar(select(Category).where(Category.tenant_id == user.tenant_id)) is not None
            assert admin.scalar(select(AuditLog).where(AuditLog.user_id == user.id)) is not None
            activation_mail = admin.scalar(
                select(EmailOutbox).where(EmailOutbox.aggregate_id == challenge["activation_id"])
            )
            assert activation_mail.status == "cancelled"
            assert activation_mail.payload_encrypted is None


def test_wrong_code_locks_after_five_attempts_without_binding_license(email_sink, admin_sessions):
    code, license_id = seed_license()
    db = SessionLocal()
    try:
        challenge = start(db, code)
    finally:
        db.close()

    for _ in range(5):
        db = SessionLocal()
        try:
            with pytest.raises(HTTPException):
                activation_service.confirm_activation(db, challenge["activation_id"], "000000" if email_sink[0][1] != "000000" else "999999")
        finally:
            db.close()

    with admin_sessions() as admin:
        activation = admin.get(PendingActivation, challenge["activation_id"])
        assert activation.status == "locked"
        assert activation.attempt_count == 5
        assert admin.get(License, license_id).tenant_id is None
        assert admin.scalar(select(User).where(User.email_lookup_hash == activation.email_lookup_hash)) is None


def test_resend_cooldown_invalidates_old_code_and_consumes_new_code_once(monkeypatch, email_sink, admin_sessions):
    code, license_id = seed_license()
    db = SessionLocal()
    try:
        challenge = start(db, code)
    finally:
        db.close()
    activation_id = challenge["activation_id"]

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc:
            activation_service.resend_activation(db, activation_id)
        assert exc.value.status_code == 429
    finally:
        db.close()

    with admin_sessions() as admin:
        admin.execute(
            text("UPDATE pending_activations SET last_sent_at = now() - interval '61 seconds' WHERE id = :id"),
            {"id": activation_id},
        )
        admin.commit()
    db = SessionLocal()
    try:
        activation_service.resend_activation(db, activation_id)
    finally:
        db.close()
    first, second = email_sink[0][1], email_sink[1][1]
    assert first != second

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            activation_service.confirm_activation(db, activation_id, first)
    finally:
        db.close()
    db = SessionLocal()
    try:
        activation_service.confirm_activation(db, activation_id, second)
    finally:
        db.close()
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            activation_service.confirm_activation(db, activation_id, second)
    finally:
        db.close()
    with admin_sessions() as admin:
        assert admin.get(License, license_id).tenant_id is not None


def test_expired_activation_does_not_consume_license_and_can_restart(email_sink, admin_sessions):
    code, license_id = seed_license()
    db = SessionLocal()
    try:
        challenge = start(db, code)
    finally:
        db.close()
    with admin_sessions() as admin:
        admin.execute(
            text("UPDATE pending_activations SET expires_at = now() - interval '1 second', last_sent_at = now() - interval '61 seconds' WHERE id = :id"),
            {"id": challenge["activation_id"]},
        )
        admin.commit()
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc:
            activation_service.confirm_activation(db, challenge["activation_id"], email_sink[0][1])
        assert exc.value.status_code == 410
    finally:
        db.close()
    with admin_sessions() as admin:
        assert admin.get(License, license_id).tenant_id is None
    db = SessionLocal()
    try:
        restarted = start(db, code)
        assert restarted["activation_id"] == challenge["activation_id"]
    finally:
        db.close()


def test_changed_activation_details_during_cooldown_preserve_original_code(email_sink, admin_sessions):
    code, license_id = seed_license()
    original_email = f"original-{uuid.uuid4().hex[:8]}@example.com"
    original_name = "Pessoa Original"
    original_password = "SenhaOriginal#2026"
    db = SessionLocal()
    try:
        challenge = activation_service.start_activation(
            db,
            name=original_name,
            email=original_email,
            password=original_password,
            license_code=code,
        )
    finally:
        db.close()
    original_code = email_sink[0][1]

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            activation_service.confirm_activation(
                db, challenge["activation_id"], "000000" if original_code != "000000" else "000001"
            )
    finally:
        db.close()

    with admin_sessions() as admin:
        before = admin.get(PendingActivation, challenge["activation_id"])
        original_state = (
            before.license_id,
            before.license_code_hash,
            before.email_encrypted,
            before.email_lookup_hash,
            before.name_encrypted,
            before.password_hash,
            before.verification_code_hash,
            before.expires_at,
            before.attempt_count,
            before.last_sent_at,
            before.status,
            before.consumed_at,
            before.created_at,
            before.updated_at,
        )
        assert before.attempt_count == 1

    changed_email = f"changed-{uuid.uuid4().hex[:8]}@example.com"
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc:
            activation_service.start_activation(
                db,
                name="Pessoa Nova",
                email=changed_email,
                password="SenhaNova#2026",
                license_code=code,
            )
        assert exc.value.status_code == 429
        assert int(exc.value.headers["Retry-After"]) > 0
        assert changed_email not in exc.value.detail
        assert original_code not in exc.value.detail
    finally:
        db.close()

    with admin_sessions() as admin:
        after = admin.get(PendingActivation, challenge["activation_id"])
        assert (
            after.license_id,
            after.license_code_hash,
            after.email_encrypted,
            after.email_lookup_hash,
            after.name_encrypted,
            after.password_hash,
            after.verification_code_hash,
            after.expires_at,
            after.attempt_count,
            after.last_sent_at,
            after.status,
            after.consumed_at,
            after.created_at,
            after.updated_at,
        ) == original_state
        assert admin.get(License, license_id).tenant_id is None
        assert admin.scalar(select(User).where(User.email_lookup_hash == email_lookup_hash(changed_email))) is None
    assert len(email_sink) == 1

    db = SessionLocal()
    try:
        _token, auth = activation_service.confirm_activation(db, challenge["activation_id"], original_code)
        assert auth["user"]["email"] == original_email
        assert auth["user"]["name"] == original_name
    finally:
        db.close()


def test_changed_activation_details_after_cooldown_replace_and_invalidate_old_code(email_sink, admin_sessions):
    code, license_id = seed_license()
    original_email = f"original-{uuid.uuid4().hex[:8]}@example.com"
    db = SessionLocal()
    try:
        challenge = activation_service.start_activation(
            db,
            name="Pessoa Original",
            email=original_email,
            password="SenhaOriginal#2026",
            license_code=code,
        )
    finally:
        db.close()
    original_code = email_sink[0][1]

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            activation_service.confirm_activation(
                db, challenge["activation_id"], "000000" if original_code != "000000" else "000001"
            )
    finally:
        db.close()
    with admin_sessions() as admin:
        before = admin.get(PendingActivation, challenge["activation_id"])
        original_mail = admin.scalar(
            select(EmailOutbox).where(EmailOutbox.aggregate_id == before.id)
        )
        original_mail_id = original_mail.id
        previous_hash = before.verification_code_hash
        previous_expiry = before.expires_at
        admin.execute(
            text("UPDATE pending_activations SET last_sent_at = now() - interval '61 seconds' WHERE id = :id"),
            {"id": challenge["activation_id"]},
        )
        admin.commit()

    changed_email = f"changed-{uuid.uuid4().hex[:8]}@example.com"
    db = SessionLocal()
    try:
        replacement = activation_service.start_activation(
            db,
            name="Pessoa Nova",
            email=changed_email,
            password="SenhaNova#2026",
            license_code=code,
        )
    finally:
        db.close()
    new_code = email_sink[-1][1]
    assert len(email_sink) == 2
    assert replacement["activation_id"] == challenge["activation_id"]
    assert replacement["email_masked"] != challenge["email_masked"]
    assert new_code != original_code

    with admin_sessions() as admin:
        activation = admin.get(PendingActivation, challenge["activation_id"])
        assert activation.email_lookup_hash == email_lookup_hash(changed_email)
        assert activation.verification_code_hash != previous_hash
        assert activation.expires_at > previous_expiry
        assert activation.attempt_count == 0
        assert activation.status == "pending"
        old_mail = admin.get(EmailOutbox, original_mail_id)
        assert old_mail.status == "cancelled"
        assert old_mail.payload_encrypted is None

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            activation_service.confirm_activation(db, challenge["activation_id"], original_code)
    finally:
        db.close()
    db = SessionLocal()
    try:
        _token, auth = activation_service.confirm_activation(db, challenge["activation_id"], new_code)
        assert auth["user"]["email"] == changed_email
        assert auth["user"]["name"] == "Pessoa Nova"
    finally:
        db.close()
    with admin_sessions() as admin:
        license_row = admin.get(License, license_id)
        assert license_row.tenant_id is not None
        assert admin.scalar(select(func.count()).select_from(User).where(User.tenant_id == license_row.tenant_id)) == 1
        assert admin.scalar(select(func.count()).select_from(Tenant).where(Tenant.id == license_row.tenant_id)) == 1


def test_code_is_bound_to_one_activation(email_sink):
    code_a, _ = seed_license()
    code_b, _ = seed_license()
    db = SessionLocal()
    try:
        challenge_a = start(db, code_a)
    finally:
        db.close()
    db = SessionLocal()
    try:
        challenge_b = start(db, code_b)
    finally:
        db.close()

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            activation_service.confirm_activation(db, challenge_b["activation_id"], email_sink[0][1])
    finally:
        db.close()
    db = SessionLocal()
    try:
        activation_service.confirm_activation(db, challenge_b["activation_id"], email_sink[1][1])
    finally:
        db.close()


def test_activation_rls_requires_opaque_id_or_visible_license_context(email_sink):
    code, _ = seed_license()
    db = SessionLocal()
    try:
        challenge = start(db, code)
    finally:
        db.close()

    db = SessionLocal()
    try:
        assert db.scalar(select(PendingActivation)) is None
    finally:
        db.close()
    db = SessionLocal()
    try:
        set_db_context(db, license_code_hash=license_code_hash(code))
        found = db.scalar(select(PendingActivation).where(PendingActivation.id == challenge["activation_id"]))
        assert found is not None
    finally:
        db.close()
    db = SessionLocal()
    try:
        set_db_context(db, pending_activation_id=uuid.uuid4())
        assert db.scalar(select(PendingActivation).where(PendingActivation.id == challenge["activation_id"])) is None
    finally:
        db.close()


def test_email_mismatch_suspended_and_bound_licenses_are_rejected(email_sink):
    licensed_email = f"buyer-{uuid.uuid4().hex[:8]}@example.test"
    code, license_id = seed_license(buyer_email=licensed_email)
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            start(db, code, f"other-{uuid.uuid4().hex[:8]}@example.test")
    finally:
        db.close()
    suspended_code, suspended_id, suspended_order_id, suspended_provider = seed_ordered_license()
    db = SessionLocal()
    try:
        set_db_context(db, payment_provider=suspended_provider, payment_order_id=suspended_order_id)
        suspended_row = db.get(License, suspended_id)
        suspended_row.status = "suspended"
        suspended_row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            start(db, suspended_code)
    finally:
        db.close()

    cancelled_code, cancelled_id, order_id, provider = seed_ordered_license()
    db = SessionLocal()
    try:
        set_db_context(db, payment_provider=provider, payment_order_id=order_id)
        license_row = db.get(License, cancelled_id)
        license_row.status = "cancelled"
        license_row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            start(db, cancelled_code)
    finally:
        db.close()

    already_used_code, _ = seed_license()
    db = SessionLocal()
    try:
        used_challenge = start(db, already_used_code)
        activation_service.confirm_activation(db, used_challenge["activation_id"], email_sink[-1][1])
    finally:
        db.close()
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException):
            start(db, already_used_code)
    finally:
        db.close()


def test_existing_account_is_not_revealed_or_duplicated(admin_sessions, email_sink):
    email = f"existing-{uuid.uuid4().hex[:8]}@example.test"
    code, _ = seed_license()
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    with admin_sessions() as admin:
        admin.execute(
            text("INSERT INTO tenants (id, name, currency, timezone) VALUES (:id, 'Existing', 'BRL', 'America/Sao_Paulo')"),
            {"id": tenant_id},
        )
        admin.execute(
            text("""INSERT INTO users (id, tenant_id, email_encrypted, email_lookup_hash, email_masked,
            name_encrypted, password_hash, role, status, theme, email_verified_at)
            VALUES (:id, :tenant, 'encrypted', :email_hash, 'ex***@example.test', 'encrypted', 'argon-hash',
            'owner', 'active', 'claro', now())"""),
            {"id": user_id, "tenant": tenant_id, "email_hash": email_lookup_hash(email)},
        )
        admin.commit()
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc:
            start(db, code, email)
        assert exc.value.status_code == 400
        assert "existing" not in exc.value.detail.lower()
    finally:
        db.close()


def test_outbox_insert_and_confirmation_commit_are_atomic(monkeypatch, email_sink, admin_sessions):
    code, license_id = seed_license()
    with admin_sessions() as admin:
        baseline_tenants = admin.scalar(text("SELECT count(*) FROM tenants"))
        baseline_categories = admin.scalar(text("SELECT count(*) FROM categories"))
        baseline_outbox = admin.scalar(select(func.count()).select_from(EmailOutbox))
    monkeypatch.setattr(
        activation_service.email_outbox_service,
        "enqueue_email",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("outbox unavailable")),
    )
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError):
            start(db, code)
    finally:
        db.rollback()
        db.close()
    with admin_sessions() as admin:
        activation = admin.scalar(select(PendingActivation).where(PendingActivation.license_id == license_id))
        assert activation is None
        assert admin.scalar(select(func.count()).select_from(EmailOutbox)) == baseline_outbox
        assert admin.get(License, license_id).tenant_id is None

    # A transaction commit failure after both rows were flushed must leave neither row.
    original_commit = Session.commit
    fail_start_commit = {"active": True}
    def fail_activation_commit(session):
        if fail_start_commit["active"] and session.info.get("rls_context", {}).get("pending_activation_id"):
            fail_start_commit["active"] = False
            raise RuntimeError("simulated activation commit failure")
        return original_commit(session)
    monkeypatch.setattr(Session, "commit", fail_activation_commit)
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError):
            start(db, code)
    finally:
        db.rollback()
        db.close()
    monkeypatch.setattr(Session, "commit", original_commit)
    with admin_sessions() as admin:
        assert admin.scalar(select(PendingActivation).where(PendingActivation.license_id == license_id)) is None
        assert admin.scalar(select(func.count()).select_from(EmailOutbox)) == baseline_outbox

    monkeypatch.setattr(activation_service.email_outbox_service, "enqueue_email", email_sink.enqueue)
    db = SessionLocal()
    try:
        challenge = start(db, code)
    finally:
        db.close()
    activation_id = challenge["activation_id"]
    with admin_sessions() as admin:
        admin.execute(
            text("UPDATE pending_activations SET last_sent_at = now() - interval '61 seconds' WHERE id = :id"),
            {"id": activation_id},
        )
        admin.commit()
    db = SessionLocal()
    try:
        activation_service.resend_activation(db, activation_id)
    finally:
        db.close()

    original_commit = Session.commit
    fail_once = {"active": True}

    def fail_confirmation_commit(session):
        if fail_once["active"] and str(session.info.get("rls_context", {}).get("pending_activation_id")) == str(activation_id):
            fail_once["active"] = False
            raise RuntimeError("simulated commit failure")
        return original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_confirmation_commit)
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError):
            activation_service.confirm_activation(db, activation_id, email_sink[-1][1])
    finally:
        db.close()
    with admin_sessions() as admin:
        activation = admin.get(PendingActivation, activation_id)
        assert activation.status == "pending"
        assert admin.get(License, license_id).tenant_id is None
        assert admin.scalar(select(User).where(User.email_lookup_hash == activation.email_lookup_hash)) is None
        assert admin.scalar(
            select(Tenant).join(User, Tenant.id == User.tenant_id).where(User.email_lookup_hash == activation.email_lookup_hash)
        ) is None
        assert admin.scalar(
            select(UserSession).join(User).where(User.email_lookup_hash == activation.email_lookup_hash)
        ) is None
        assert admin.scalar(text("SELECT count(*) FROM tenants")) == baseline_tenants
        assert admin.scalar(text("SELECT count(*) FROM categories")) == baseline_categories


def test_two_concurrent_confirmations_create_one_account_and_session(email_sink, admin_sessions):
    code, license_id = seed_license()
    db = SessionLocal()
    try:
        challenge = start(db, code)
    finally:
        db.close()

    def confirm():
        session = SessionLocal()
        try:
            return activation_service.confirm_activation(session, challenge["activation_id"], email_sink[0][1])
        except HTTPException as exc:
            return exc.status_code
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(confirm) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    successes = [result for result in results if isinstance(result, tuple)]
    assert len(successes) == 1
    with admin_sessions() as admin:
        activation = admin.get(PendingActivation, challenge["activation_id"])
        assert activation.status == "consumed"
        license_row = admin.get(License, license_id)
        assert license_row.tenant_id is not None
        users = admin.scalar(
            select(func.count()).select_from(User).where(User.email_lookup_hash == activation.email_lookup_hash)
        )
        tenants = admin.scalar(select(func.count()).select_from(Tenant).where(Tenant.id == license_row.tenant_id))
        sessions = admin.scalar(
            select(func.count()).select_from(UserSession).where(
                UserSession.user_id == select(User.id)
                .where(User.email_lookup_hash == activation.email_lookup_hash)
                .scalar_subquery()
            )
        )
        assert (users, tenants, sessions) == (1, 1, 1)


def _run_start_confirm_lock_order_race(*, restart: bool, email_sink: list[tuple[str, str]]):
    """Hold a real PostgreSQL license lock while confirmation reaches that same row."""
    code, license_id = seed_license()
    initial_email = f"race-{uuid.uuid4().hex[:10]}@example.com"
    db = SessionLocal()
    try:
        challenge = activation_service.start_activation(
            db,
            name="Pessoa de Teste",
            email=initial_email,
            password="SenhaSegura#2026",
            license_code=code,
        )
    finally:
        db.close()
    verification_code = email_sink[-1][1]

    worker = local()
    start_has_license_lock = Event()
    allow_start_to_continue = Event()
    confirm_reached_license = Event()

    def before_cursor_execute(_connection, _cursor, statement, _parameters, _context, _many):
        if getattr(worker, "kind", None) == "confirm":
            lowered = statement.lower()
            if "from licenses" in lowered and "for update" in lowered:
                confirm_reached_license.set()

    def after_cursor_execute(_connection, _cursor, statement, _parameters, _context, _many):
        if getattr(worker, "kind", None) == "start":
            lowered = statement.lower()
            if "from licenses" in lowered and "for update" in lowered and not start_has_license_lock.is_set():
                start_has_license_lock.set()
                if not allow_start_to_continue.wait(timeout=8):
                    raise TimeoutError("test did not release the license lock holder")

    def run_start():
        worker.kind = "start"
        session = SessionLocal()
        try:
            try:
                return activation_service.start_activation(
                    session,
                    name="Outra Pessoa" if restart else "Pessoa de Teste",
                    email=f"restart-{uuid.uuid4().hex[:10]}@example.com" if restart else initial_email,
                    password="OutraSenha#2026" if restart else "SenhaSegura#2026",
                    license_code=code,
                )
            except HTTPException as exc:
                return exc.status_code
        finally:
            session.close()

    def run_confirm():
        worker.kind = "confirm"
        session = SessionLocal()
        try:
            return activation_service.confirm_activation(
                session, challenge["activation_id"], verification_code
            )
        except HTTPException as exc:
            return exc.status_code
        finally:
            session.close()

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            start_future = pool.submit(run_start)
            assert start_has_license_lock.wait(timeout=5), "start did not acquire license row lock"
            confirm_future = pool.submit(run_confirm)
            assert confirm_reached_license.wait(timeout=5), "confirmation did not try the license row lock"
            allow_start_to_continue.set()
            start_result = start_future.result(timeout=10)
            confirm_result = confirm_future.result(timeout=10)
    finally:
        allow_start_to_continue.set()
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine, "after_cursor_execute", after_cursor_execute)

    return code, license_id, challenge, start_result, confirm_result


def test_start_and_confirmation_use_license_then_activation_lock_order(email_sink, admin_sessions):
    _code, license_id, challenge, _start_result, confirm_result = _run_start_confirm_lock_order_race(
        restart=False, email_sink=email_sink
    )
    assert isinstance(confirm_result, tuple)
    with admin_sessions() as admin:
        license_row = admin.get(License, license_id)
        activation = admin.get(PendingActivation, challenge["activation_id"])
        assert license_row.status == "active"
        assert activation.status == "consumed"
        assert admin.scalar(select(func.count()).select_from(User).where(User.tenant_id == license_row.tenant_id)) == 1
        assert admin.scalar(select(func.count()).select_from(Tenant).where(Tenant.id == license_row.tenant_id)) == 1


def test_restart_racing_confirmation_is_limited_and_original_code_succeeds(email_sink, admin_sessions):
    _code, license_id, challenge, start_result, confirm_result = _run_start_confirm_lock_order_race(
        restart=True, email_sink=email_sink
    )
    assert start_result == 429
    assert isinstance(confirm_result, tuple)
    with admin_sessions() as admin:
        license_row = admin.get(License, license_id)
        activation = admin.get(PendingActivation, challenge["activation_id"])
        assert license_row.tenant_id is not None
        assert license_row.status == "active"
        assert activation.status == "consumed"
        assert activation.verification_code_hash is None
        assert admin.scalar(
            select(func.count()).select_from(User).where(User.email_lookup_hash == activation.email_lookup_hash)
        ) == 1
        assert admin.scalar(select(func.count()).select_from(Tenant).where(Tenant.id == license_row.tenant_id)) == 1


def test_resend_racing_confirmation_serializes_on_activation_row(email_sink, admin_sessions):
    code, license_id = seed_license()
    db = SessionLocal()
    try:
        challenge = start(db, code)
    finally:
        db.close()
    with admin_sessions() as admin:
        admin.execute(
            text("UPDATE pending_activations SET last_sent_at = now() - interval '61 seconds' WHERE id = :id"),
            {"id": challenge["activation_id"]},
        )
        admin.commit()

    old_code = email_sink[0][1]
    worker = local()
    resend_has_activation_lock = Event()
    allow_resend_to_commit = Event()
    confirm_waiting_for_activation = Event()

    def before_cursor_execute(_connection, _cursor, statement, _parameters, _context, _many):
        lowered = statement.lower()
        if getattr(worker, "kind", None) == "confirm" and "from pending_activations" in lowered and "for update" in lowered:
            confirm_waiting_for_activation.set()

    def after_cursor_execute(_connection, _cursor, statement, _parameters, _context, _many):
        lowered = statement.lower()
        if (
            getattr(worker, "kind", None) == "resend"
            and "from pending_activations" in lowered
            and "for update" in lowered
            and not resend_has_activation_lock.is_set()
        ):
            resend_has_activation_lock.set()
            if not allow_resend_to_commit.wait(timeout=8):
                raise TimeoutError("test did not release the activation row lock holder")

    def run_resend():
        worker.kind = "resend"
        session = SessionLocal()
        try:
            return activation_service.resend_activation(session, challenge["activation_id"])
        finally:
            session.close()

    def run_confirm_old_code():
        worker.kind = "confirm"
        session = SessionLocal()
        try:
            return activation_service.confirm_activation(session, challenge["activation_id"], old_code)
        except HTTPException as exc:
            return exc.status_code
        finally:
            session.close()

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            resend_future = pool.submit(run_resend)
            assert resend_has_activation_lock.wait(timeout=5), "resend did not acquire activation row lock"
            confirm_future = pool.submit(run_confirm_old_code)
            assert confirm_waiting_for_activation.wait(timeout=5), "confirmation did not reach activation row lock"
            allow_resend_to_commit.set()
            resend_future.result(timeout=10)
            assert confirm_future.result(timeout=10) == 400
    finally:
        allow_resend_to_commit.set()
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine, "after_cursor_execute", after_cursor_execute)

    new_code = email_sink[-1][1]
    assert new_code != old_code
    db = SessionLocal()
    try:
        activation_service.confirm_activation(db, challenge["activation_id"], new_code)
    finally:
        db.close()
    with admin_sessions() as admin:
        license_row = admin.get(License, license_id)
        assert license_row.tenant_id is not None
        assert admin.scalar(select(func.count()).select_from(User).where(User.tenant_id == license_row.tenant_id)) == 1
        assert admin.scalar(select(func.count()).select_from(Tenant).where(Tenant.id == license_row.tenant_id)) == 1


def test_z_legacy_user_email_verification_is_backfilled(integration_database, admin_sessions):
    from alembic import command
    from alembic.config import Config
    from app.core.database import set_db_context
    from app.core.field_encryption import encrypt_text, license_code_hash, masked_email
    from app.core.security import hash_password
    from app.services.license_service import bind_license

    config = Config("alembic.ini")
    command.downgrade(config, "20261031_04")
    code, license_id = seed_license()
    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        with migration_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261031_04"
            assert connection.scalar(text("SELECT to_regclass('public.pending_activations')")) is None
        tenant_id = uuid.uuid4()
        legacy_email = f"legacy-{uuid.uuid4().hex[:10]}@example.com"
        email_hash = email_lookup_hash(legacy_email)
        password = "SenhaLegada#2026"
        db = SessionLocal()
        try:
            set_db_context(db, tenant_id=tenant_id)
            db.add(Tenant(id=tenant_id, name="Legacy", currency="BRL", timezone="America/Sao_Paulo"))
            db.flush()
            set_db_context(db, license_code_hash=license_code_hash(code))
            license_row = db.get(License, license_id)
            bind_license(db, license_row, tenant_id, email_hash)
            db.commit()
        finally:
            db.close()

        with migration_engine.begin() as connection:
            user_id = uuid.uuid4()
            connection.execute(
                text("""INSERT INTO users (id, tenant_id, email_encrypted, email_lookup_hash, email_masked,
                name_encrypted, password_hash, role, status, theme, email_verified_at)
                VALUES (:id, :tenant, :email_encrypted, :email_hash, :email_masked, :name_encrypted, :password,
                'owner', 'active', 'claro', NULL)"""),
                {
                    "id": user_id,
                    "tenant": tenant_id,
                    "email_encrypted": encrypt_text(legacy_email, "users.email"),
                    "email_hash": email_hash,
                    "email_masked": masked_email(legacy_email),
                    "name_encrypted": encrypt_text("Usuário legado", "users.name"),
                    "password": hash_password(password),
                },
            )
        command.upgrade(config, "head")
        with migration_engine.connect() as connection:
            verified_at = connection.scalar(text("SELECT email_verified_at FROM users WHERE id = :id"), {"id": user_id})
            pending_table = connection.scalar(text("SELECT to_regclass('public.pending_activations')"))
            assert verified_at is not None
            assert pending_table == "pending_activations"
        with TestClient(main.app) as client:
            login = client.post("/api/v1/auth/login", json={"email": legacy_email, "password": password})
            assert login.status_code == 200, login.text
            assert "fh_session=" in login.headers.get("set-cookie", "")
            with migration_engine.begin() as connection:
                connection.execute(
                    text("UPDATE users SET email_verified_at = NULL WHERE id = :id"), {"id": user_id}
                )
            with admin_sessions() as admin:
                session_count = admin.scalar(
                    select(func.count()).select_from(UserSession).where(UserSession.user_id == user_id)
                )
            unverified_login = client.post(
                "/api/v1/auth/login", json={"email": legacy_email, "password": password}
            )
            assert unverified_login.status_code == 401
            with admin_sessions() as admin:
                assert admin.scalar(
                    select(func.count()).select_from(UserSession).where(UserSession.user_id == user_id)
                ) == session_count
            with migration_engine.begin() as connection:
                connection.execute(
                    text("UPDATE users SET email_verified_at = created_at WHERE id = :id"), {"id": user_id}
                )
    finally:
        migration_engine.dispose()
