from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import decrypt_text, email_lookup_hash, encrypt_text
from app.core.rate_limit import limiter
from app.main import app
from app.models.bill import Bill
from app.models.category import Category
from app.models.email_outbox import EmailOutbox
from app.models.idempotency import IdempotencyRecord
from app.models.license import License
from app.models.login_lockout import LoginLockoutState
from app.models.order import Order
from app.models.password_reset import PasswordResetToken
from app.models.privacy import DataDeletionTombstone, PrivacyRequest
from app.models.product import Product
from app.models.session import UserSession
from app.models.tenant import Tenant
from app.models.transaction import Transaction
from app.models.user import User
from app.services import auth_service, email_outbox_service, license_service, login_lockout_service, support_service
from tests.integration.test_financial_domain import (
    PASSWORD,
    add_member,
    category_id,
    client_for,
    create_tenant_user,
    tenant_today,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _migrated_database(integration_database):
    yield


@pytest.fixture(autouse=True)
def _disable_rate_limit(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)


def count(model, tenant_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def user_email(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        user = db.get(User, user_id)
        return decrypt_text(user.email_encrypted, "users.email") or ""


def create_tenant_user_with_order() -> tuple[uuid.UUID, uuid.UUID, str, uuid.UUID, uuid.UUID]:
    email = f"privacy-owner-{uuid.uuid4().hex[:10]}@example.com"
    tenant_id = uuid.uuid4()
    provider = f"privacy-provider-{uuid.uuid4().hex[:8]}"
    code = f"FH-PRIV-{uuid.uuid4().hex[:12].upper()}"
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=f"privacy-product-{uuid.uuid4().hex[:12]}",
            name="Produto privacidade",
            price_cents=19990,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.flush()
        set_db_context(db, catalog_write="true", payment_provider=provider)
        order = Order(
            provider=provider,
            external_order_id=f"tx-{uuid.uuid4()}",
            product_id=product.id,
            buyer_email_encrypted=encrypt_text(email, "orders.buyer_email"),
            buyer_email_hash=email_lookup_hash(email),
            amount_cents=19990,
            currency="BRL",
            status="paid",
            external_customer_id=f"customer-{uuid.uuid4().hex[:8]}",
        )
        db.add(order)
        db.flush()
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Família privacidade", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        user = User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(email, "users.email"),
            email_lookup_hash=email_lookup_hash(email),
            email_masked="p***@example.com",
            name_encrypted=encrypt_text("Pessoa Privacidade", "users.name"),
            password_hash=auth_service.hash_password(PASSWORD),
            role="owner",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        set_db_context(
            db,
            tenant_id=tenant_id,
            catalog_write="true",
            payment_provider=provider,
            license_code_hash=license_service.license_code_hash(code),
        )
        license_row, _ = license_service.issue_license(
            db, product, order_id=order.id, code=code, buyer_email=email
        )
        license_service.bind_license(db, license_row, tenant_id, email_lookup_hash(email))
        auth_service._seed_categories(db, tenant_id)
        token, _ = auth_service._create_session(db, user)
        db.commit()
        return tenant_id, user.id, token, product.id, order.id


def create_operator(email: str, role: str = "support_operator") -> str:
    with SessionLocal() as db:
        support_service.provision_support_operator(
            db,
            email=email,
            name="Operador Privacidade",
            role=role,
            password="SupportPass#2026",
            active=True,
            apply=True,
        )
        db.commit()
    return email


def support_client(email: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/support/auth/login",
        json={"email": email, "password": "SupportPass#2026"},
    )
    assert response.status_code == 200, response.text
    return client


def test_member_erasure_anonymizes_own_data_and_preserves_tenant_finances():
    tenant_id, owner_id, owner_token, product_id = create_tenant_user()
    member_id, member_token = add_member(tenant_id)
    member = client_for(member_token)
    owner = client_for(owner_token)
    email = user_email(member_id, tenant_id)

    created = member.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "10.00",
            "occurred_on": tenant_today().isoformat(),
            "description": "Despesa do member",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201

    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        reset_id = uuid.uuid4()
        reset = PasswordResetToken(
            id=reset_id,
            tenant_id=tenant_id,
            user_id=member_id,
            token_hash=uuid.uuid4().hex * 2,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add(reset)
        outbox = email_outbox_service.enqueue_email(
            db,
            event_type="password_reset",
            payload={"to": email, "token": "token-ficticio"},
            idempotency_key=f"privacy-reset:{reset_id}",
            aggregate_id=reset_id,
        )
        db.commit()
        outbox_id = outbox.id
        login_lockout_service.record_failure(db, email)
        db.commit()

    response = member.post(
        "/api/v1/privacy/requests",
        json={"password": PASSWORD, "reason": "Encerrar minha participação"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["scope"] == "user"
    assert body["protocol"].startswith("PRIV-")

    assert member.get("/api/v1/auth/me").status_code == 401
    login = TestClient(app).post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code != 200
    assert owner.get("/api/v1/auth/me").status_code == 200

    financial = owner.get("/api/v1/transactions").json()
    assert any(item["description"] == "Despesa do member" for item in financial)

    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        user = db.get(User, member_id)
        assert user.status == "disabled"
        assert "deleted-" in (decrypt_text(user.email_encrypted, "users.email") or "")
        assert db.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == member_id)) == 0
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.user_id == member_id)) == 0
        assert db.scalar(
            select(func.count()).select_from(LoginLockoutState).where(
                LoginLockoutState.key_hash == login_lockout_service.lockout_key(email)
            )
        ) == 0
        request = db.scalar(select(PrivacyRequest).where(PrivacyRequest.protocol == body["protocol"]))
        assert request is not None and request.status == "completed"
        assert db.scalar(select(func.count()).select_from(DataDeletionTombstone)) == 1
        set_db_context(db, support_operator_id=uuid.uuid4())
        outbox_row = db.execute(
            select(EmailOutbox.status, EmailOutbox.last_error).where(EmailOutbox.id == outbox_id)
        ).one()
        assert outbox_row.status == "cancelled"
        assert outbox_row.last_error == "privacy_erasure"


def test_pending_outbox_is_cancelled_before_worker_send():
    tenant_id, _, _, _ = create_tenant_user()
    member_id, _ = add_member(tenant_id)
    email = user_email(member_id, tenant_id)
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        reset_id = uuid.uuid4()
        db.add(
            PasswordResetToken(
                id=reset_id,
                tenant_id=tenant_id,
                user_id=member_id,
                token_hash=uuid.uuid4().hex * 2,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        outbox = email_outbox_service.enqueue_email(
            db,
            event_type="password_reset",
            payload={"to": email, "token": "token-ficticio"},
            idempotency_key=f"privacy-processing:{reset_id}",
            aggregate_id=reset_id,
        )
        db.commit()
        outbox_id = outbox.id

    from app.services import privacy_service

    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        privacy_service._anonymize_user(db, db.get(User, member_id))
        db.commit()

    with SessionLocal() as db:
        set_db_context(db, support_operator_id=uuid.uuid4())
        assert db.execute(
            select(EmailOutbox.status).where(EmailOutbox.id == outbox_id)
        ).scalar_one() == "cancelled"


def test_owner_sole_erasure_closes_tenant_and_anonymizes_commercial_records():
    tenant_id, owner_id, token, product_id, order_id = create_tenant_user_with_order()
    owner = client_for(token)
    email = user_email(owner_id, tenant_id)
    created = owner.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "42.00",
            "occurred_on": tenant_today().isoformat(),
            "description": "Despesa antes da exclusão",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201

    response = owner.post(
        "/api/v1/privacy/requests", json={"password": PASSWORD, "reason": "Encerrar conta"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["scope"] == "tenant"
    assert owner.get("/api/v1/auth/me").status_code == 401
    assert TestClient(app).post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).status_code != 200

    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        assert db.get(Tenant, tenant_id).name == "Conta encerrada"
        assert db.get(User, owner_id).status == "disabled"
        assert db.scalar(select(func.count()).select_from(Transaction)) == 0
        assert db.scalar(select(func.count()).select_from(Bill)) == 0
        assert db.scalar(select(func.count()).select_from(Category)) == 0
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
        request = db.scalar(select(PrivacyRequest).where(PrivacyRequest.protocol == body["protocol"]))
        assert request.status == "completed"
        assert db.scalar(select(func.count()).select_from(DataDeletionTombstone)) == 1

    with SessionLocal() as db:
        set_db_context(db, support_operator_id=uuid.uuid4())
        order = db.get(Order, order_id)
        license_row = db.scalar(select(License).where(License.order_id == order_id))
        assert order.buyer_email_encrypted is None
        assert order.buyer_email_hash is None
        assert order.external_customer_id is None
        assert license_row.status == "cancelled"
        assert license_row.tenant_id is None
        assert license_row.bound_email_hash is None


def test_owner_with_active_member_is_sent_to_support_review_and_can_be_approved_after_unlink():
    tenant_id, owner_id, owner_token, _ = create_tenant_user()
    member_id, member_token = add_member(tenant_id)
    owner = client_for(owner_token)
    member = client_for(member_token)

    first = owner.post(
        "/api/v1/privacy/requests", json={"password": PASSWORD, "reason": "Encerrar família"}
    )
    assert first.status_code == 201, first.text
    request = first.json()
    assert request["status"] == "awaiting_review"
    assert request["scope"] == "tenant"

    duplicate = owner.post(
        "/api/v1/privacy/requests", json={"password": PASSWORD, "reason": "Encerrar família"}
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == request["id"]
    assert owner.get("/api/v1/auth/me").status_code == 200

    read_email = create_operator(f"privacy-read-{uuid.uuid4().hex[:8]}@example.com", "support_read")
    read_client = support_client(read_email)
    listed = read_client.get("/api/v1/support/privacy/requests")
    assert listed.status_code == 200
    assert any(item["id"] == request["id"] for item in listed.json()["items"])
    assert read_client.post(
        f"/api/v1/support/privacy/requests/{request['id']}/approve",
        json={"justification": "Tentativa de leitura não autorizada"},
    ).status_code == 403

    operator_email = create_operator(f"privacy-op-{uuid.uuid4().hex[:8]}@example.com")
    operator = support_client(operator_email)
    blocked = operator.post(
        f"/api/v1/support/privacy/requests/{request['id']}/approve",
        json={"justification": "Aprovação automática após análise"},
    )
    assert blocked.status_code == 409
    assert owner.get("/api/v1/auth/me").status_code == 200

    member_delete = member.post(
        "/api/v1/privacy/requests", json={"password": PASSWORD, "reason": "Sair do tenant"}
    )
    assert member_delete.status_code == 201
    assert member_delete.json()["status"] == "completed"

    approved = operator.post(
        f"/api/v1/support/privacy/requests/{request['id']}/approve",
        json={"justification": "Member desvinculado; encerramento aprovado"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "completed"
    assert owner.get("/api/v1/auth/me").status_code == 401


def test_privacy_request_isolation_wrong_password_and_cancel():
    tenant_a, _, token_a, _ = create_tenant_user()
    add_member(tenant_a)
    tenant_b, _, token_b, _ = create_tenant_user()
    owner_a = client_for(token_a)
    owner_b = client_for(token_b)

    wrong = owner_a.post("/api/v1/privacy/requests", json={"password": "senha-errada"})
    assert wrong.status_code == 400

    request = owner_a.post(
        "/api/v1/privacy/requests", json={"password": PASSWORD, "reason": "Solicitação cancelável"}
    ).json()
    assert request["status"] == "awaiting_review"
    assert owner_b.get(f"/api/v1/privacy/requests/{request['id']}").status_code == 404
    assert client_for(token_a).post(
        f"/api/v1/privacy/requests/{request['id']}/cancel"
    ).status_code == 200
    assert owner_a.get(f"/api/v1/privacy/requests/{request['id']}").json()["status"] == "cancelled"

    anonymous = TestClient(app).post("/api/v1/privacy/requests", json={"password": PASSWORD})
    assert anonymous.status_code == 401


def test_reapply_tombstone_after_restore_simulation_is_idempotent():
    from app.services import privacy_service

    tenant_id, owner_id, token, _, _ = create_tenant_user_with_order()
    owner = client_for(token)
    assert owner.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "15.00",
            "occurred_on": tenant_today().isoformat(),
            "description": "Registro restaurado",
        },
    ).status_code == 201

    with SessionLocal() as db:
        privacy_service.reapply_tombstone(
            db, tenant_id=tenant_id, user_id=owner_id, scope="tenant"
        )

    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        assert db.get(Tenant, tenant_id).name == "Conta encerrada"
        assert db.get(User, owner_id).status == "disabled"
        assert db.scalar(select(func.count()).select_from(Transaction)) == 0
        assert db.scalar(select(func.count()).select_from(DataDeletionTombstone)) == 1
