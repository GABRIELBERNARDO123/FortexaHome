from __future__ import annotations

import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import rate_limit
from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import email_lookup_hash, encrypt_text, license_code_hash, masked_email
from app.core.security import hash_password
from app.main import app
from app.models.audit_log import AuditLog
from app.models.license import License
from app.models.login_lockout import LoginLockoutState
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.user import User
from app.services import auth_service, license_service, login_lockout_service

pytestmark = pytest.mark.integration
PASSWORD = "SenhaSegura#2026"


def create_customer() -> tuple[str, uuid.UUID, uuid.UUID]:
    email = f"lockout-{uuid.uuid4().hex[:12]}@example.com"
    tenant_id = uuid.uuid4()
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=f"lockout-{uuid.uuid4().hex[:10]}",
            name="Produto lockout",
            price_cents=19990,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.flush()
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Família lockout", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        user = User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(email, "users.email"),
            email_lookup_hash=email_lookup_hash(email),
            email_masked=masked_email(email),
            name_encrypted=encrypt_text("Pessoa Lockout", "users.name"),
            password_hash=hash_password(PASSWORD),
            role="owner",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        code = f"FH-LOCK-{uuid.uuid4().hex[:16].upper()}"
        set_db_context(
            db,
            tenant_id=tenant_id,
            license_code_hash=license_code_hash(code),
        )
        license_row, _ = license_service.issue_license(db, product, code=code, buyer_email=email)
        license_service.bind_license(db, license_row, tenant_id, email_lookup_hash(email))
        auth_service._seed_categories(db, tenant_id)
        db.commit()
        return email, user.id, tenant_id


def state(email: str) -> LoginLockoutState | None:
    with SessionLocal() as db:
        return db.scalar(
            select(LoginLockoutState).where(
                LoginLockoutState.key_hash == login_lockout_service.lockout_key(email)
            )
        )


def login(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def disable_rate_limit(monkeypatch):
    monkeypatch.setattr(rate_limit.limiter, "enabled", False)


def test_fifth_failure_locks_account_and_correct_password_cannot_bypass(monkeypatch):
    disable_rate_limit(monkeypatch)
    email, user_id, tenant_id = create_customer()
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS", 1)
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS", 2)
    client = TestClient(app)

    for _ in range(4):
        assert login(client, email, "SenhaErrada#2026").status_code == 401
    fifth = login(client, email, "SenhaErrada#2026")
    assert fifth.status_code == 429
    assert int(fifth.headers["Retry-After"]) >= 1

    blocked_correct = login(client, email, PASSWORD)
    assert blocked_correct.status_code == 429
    assert blocked_correct.json()["detail"] == "Muitas tentativas de login. Tente novamente mais tarde."

    time.sleep(1.2)
    recovered = login(client, email, PASSWORD)
    assert recovered.status_code == 200, recovered.text
    row = state(email)
    assert row is not None
    assert row.failure_count == 0
    assert row.locked_until is None
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        events = list(
            db.scalars(
                select(AuditLog.event).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id == user_id,
                )
            )
        )
        assert "LOGIN_FAILED" in events
        assert "LOGIN_LOCKED" in events
        assert "LOGIN_SUCCESS" in events


def test_unknown_email_has_equivalent_lockout_and_no_enumeration(monkeypatch):
    disable_rate_limit(monkeypatch)
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS", 1)
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS", 2)
    email = f"unknown-{uuid.uuid4().hex[:12]}@example.com"
    client = TestClient(app)

    for _ in range(4):
        assert login(client, email, "SenhaErrada#2026").status_code == 401
    fifth = login(client, email, "SenhaErrada#2026")
    assert fifth.status_code == 429
    assert int(fifth.headers["Retry-After"]) >= 1
    assert fifth.json()["detail"] == "Muitas tentativas de login. Tente novamente mais tarde."
    assert state(email) is not None

    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email_lookup_hash == email_lookup_hash(email))) is None
        row = db.scalar(
            select(LoginLockoutState).where(
                LoginLockoutState.key_hash == login_lockout_service.lockout_key(email)
            )
        )
        assert row is not None and row.failure_count >= 5
        assert email not in row.key_hash


def test_success_resets_progressive_failures(monkeypatch):
    disable_rate_limit(monkeypatch)
    email, _, _ = create_customer()
    client = TestClient(app)

    for _ in range(4):
        assert login(client, email, "SenhaErrada#2026").status_code == 401
    assert login(client, email, PASSWORD).status_code == 200

    for _ in range(4):
        assert login(client, email, "SenhaErrada#2026").status_code == 401
    assert login(client, email, "SenhaErrada#2026").status_code == 429


def test_concurrent_failures_are_counted_atomically(monkeypatch):
    disable_rate_limit(monkeypatch)
    email, _, _ = create_customer()

    def attempt(_: int):
        with TestClient(app) as client:
            return login(client, email, "SenhaErrada#2026").status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(attempt, range(10)))
    assert set(statuses) <= {401, 429}
    assert 429 in statuses
    row = state(email)
    assert row is not None
    assert row.failure_count >= 5
    assert row.locked_until is not None and row.locked_until > datetime.now(timezone.utc)


def test_cooldown_is_capped_and_counter_is_bounded(monkeypatch):
    email = f"cap-{uuid.uuid4().hex[:12]}@example.com"
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_FAILURE_THRESHOLD", 2)
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS", 1)
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS", 4)
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS", 60)
    monkeypatch.setattr(login_lockout_service.settings, "LOGIN_LOCKOUT_MAX_TRACKED_FAILURES", 8)

    with SessionLocal() as db:
        for _ in range(12):
            status = login_lockout_service.record_failure(db, email)
            db.commit()
        row = db.scalar(
            select(LoginLockoutState).where(
                LoginLockoutState.key_hash == login_lockout_service.lockout_key(email)
            )
        )
        assert row is not None
        assert row.failure_count == 8
        assert status.locked_until is not None
        remaining = (status.locked_until - datetime.now(timezone.utc)).total_seconds()
        assert 0 < remaining <= 5
