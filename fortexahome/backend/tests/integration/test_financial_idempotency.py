from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import email_lookup_hash, encrypt_text, license_code_hash, masked_email
from app.core.security import hash_password, hash_token
from app.main import app
from app.models.bill import Bill
from app.models.budget import Budget
from app.models.goal_movement import GoalMovement
from app.models.idempotency import IdempotencyRecord
from app.models.license import License
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.transaction import Transaction
from app.models.user import User
from app.services import auth_service, license_service
from tests.integration.test_financial_domain import (
    add_member,
    category_id,
    client_for,
    create_tenant_user,
    tenant_today,
)

pytestmark = pytest.mark.integration
settings = get_settings()


@pytest.fixture(autouse=True)
def _migrated_database(integration_database):
    yield


def count(model, tenant_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def transaction_payload(description: str, amount: str = "100.00") -> dict:
    return {
        "kind": "expense",
        "amount": amount,
        "occurred_on": tenant_today().isoformat(),
        "description": description,
        "payment_method": "pix",
    }


def test_transaction_same_key_replays_and_different_payload_conflicts():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    key = str(uuid.uuid4())
    payload = transaction_payload("Idempotente A")
    headers = {"Idempotency-Key": key}

    first = client.post("/api/v1/transactions", json=payload, headers=headers)
    second = client.post("/api/v1/transactions", json=payload, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert count(Transaction, tenant_id) == 1

    conflict = client.post(
        "/api/v1/transactions",
        json=transaction_payload("Idempotente A", "500.00"),
        headers=headers,
    )
    assert conflict.status_code == 409
    assert count(Transaction, tenant_id) == 1


def test_transaction_failed_effect_rolls_back_idempotency_and_can_retry():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}
    income_category = category_id(client, "income")

    failed = client.post(
        "/api/v1/transactions",
        json={
            **transaction_payload("Tentativa inválida"),
            "category_id": income_category,
        },
        headers=headers,
    )
    assert failed.status_code == 400
    assert count(Transaction, tenant_id) == 0
    assert count(IdempotencyRecord, tenant_id) == 0

    retried = client.post(
        "/api/v1/transactions",
        json=transaction_payload("Tentativa corrigida"),
        headers=headers,
    )
    assert retried.status_code == 201, retried.text
    assert count(Transaction, tenant_id) == 1


def test_different_keys_same_payload_create_two_legitimate_transactions():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    payload = transaction_payload("Duas despesas legítimas")

    first = client.post(
        "/api/v1/transactions",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    second = client.post(
        "/api/v1/transactions",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert count(Transaction, tenant_id) == 2


def test_missing_key_keeps_legacy_behavior():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    payload = transaction_payload("Sem chave")

    assert client.post("/api/v1/transactions", json=payload).status_code == 201
    assert client.post("/api/v1/transactions", json=payload).status_code == 201
    assert count(Transaction, tenant_id) == 2


def test_invalid_key_is_rejected_and_raw_key_is_not_stored():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    payload = transaction_payload("Chave inválida")

    assert client.post(
        "/api/v1/transactions", json=payload, headers={"Idempotency-Key": "tem espaco"}
    ).status_code == 400
    assert client.post(
        "/api/v1/transactions", json=payload, headers={"Idempotency-Key": "x" * 129}
    ).status_code == 400

    key = str(uuid.uuid4())
    created = client.post(
        "/api/v1/transactions", json=payload, headers={"Idempotency-Key": key}
    )
    assert created.status_code == 201

    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        record = db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key_hash == hash_token(key))
        )
        assert record is not None
        assert record.key_hash != key
        assert key not in record.response_payload


def test_pay_and_unpay_same_key_replays_without_duplicate_transaction():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    bill = client.post(
        "/api/v1/bills",
        json={"name": "Conta idempotente", "amount": "77.77", "due_on": tenant_today().isoformat()},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    ).json()

    pay_key = str(uuid.uuid4())
    pay_headers = {"Idempotency-Key": pay_key}
    first_pay = client.post(f"/api/v1/bills/{bill['id']}/pay", headers=pay_headers)
    second_pay = client.post(f"/api/v1/bills/{bill['id']}/pay", headers=pay_headers)

    assert first_pay.status_code == 200 and second_pay.status_code == 200
    assert first_pay.json()["transaction_id"] == second_pay.json()["transaction_id"]
    assert count(Transaction, tenant_id) == 1

    assert client.post(
        f"/api/v1/bills/{bill['id']}/pay",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    ).status_code == 409
    assert count(Transaction, tenant_id) == 1

    unpay_key = str(uuid.uuid4())
    unpay_headers = {"Idempotency-Key": unpay_key}
    first_unpay = client.post(f"/api/v1/bills/{bill['id']}/unpay", headers=unpay_headers)
    second_unpay = client.post(f"/api/v1/bills/{bill['id']}/unpay", headers=unpay_headers)

    assert first_unpay.status_code == 200 and second_unpay.status_code == 200
    assert first_unpay.json()["status"] == "pending"
    assert count(Transaction, tenant_id) == 0
    assert client.post(
        f"/api/v1/bills/{bill['id']}/unpay",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    ).status_code == 409


def test_concurrent_pay_same_key_creates_one_transaction():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    bill = client.post(
        "/api/v1/bills",
        json={"name": "Conta concorrente", "amount": "50.00", "due_on": tenant_today().isoformat()},
    ).json()
    key = str(uuid.uuid4())

    def pay():
        return client_for(token).post(
            f"/api/v1/bills/{bill['id']}/pay",
            headers={"Idempotency-Key": key},
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(lambda _: pay(), range(10)))

    assert statuses == [200] * 10
    assert count(Transaction, tenant_id) == 1
    paid = client.get("/api/v1/bills").json()
    assert next(item for item in paid if item["id"] == bill["id"])["status"] == "paid"


def test_concurrent_goal_movement_same_key_creates_one_movement():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    goal = client.post(
        "/api/v1/goals", json={"name": "Meta concorrente", "target_amount": "1000.00"}
    ).json()
    key = str(uuid.uuid4())
    payload = {"kind": "deposit", "amount": "100.00"}

    def deposit():
        return client_for(token).post(
            f"/api/v1/goals/{goal['id']}/movements",
            json=payload,
            headers={"Idempotency-Key": key},
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(lambda _: deposit(), range(10)))

    assert statuses == [201] * 10
    assert count(GoalMovement, tenant_id) == 1
    state = next(item for item in client.get("/api/v1/goals").json() if item["id"] == goal["id"])
    assert state["saved_amount"] == "100.00"


def test_idempotency_is_scoped_by_tenant_and_user():
    tenant_a, _, token_a, _ = create_tenant_user()
    tenant_b, _, token_b, _ = create_tenant_user()
    key = str(uuid.uuid4())

    first = client_for(token_a).post(
        "/api/v1/transactions",
        json=transaction_payload("Tenant A", "10.00"),
        headers={"Idempotency-Key": key},
    )
    second = client_for(token_b).post(
        "/api/v1/transactions",
        json=transaction_payload("Tenant B", "20.00"),
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert count(Transaction, tenant_a) == 1
    assert count(Transaction, tenant_b) == 1
    assert count(IdempotencyRecord, tenant_a) == 1
    assert count(IdempotencyRecord, tenant_b) == 1

    _, member_token = add_member(tenant_a)
    member = client_for(member_token).post(
        "/api/v1/transactions",
        json=transaction_payload("Member A", "30.00"),
        headers={"Idempotency-Key": key},
    )
    assert member.status_code == 201
    assert count(Transaction, tenant_a) == 2
    assert count(IdempotencyRecord, tenant_a) == 2


def test_budget_and_recurrence_domain_constraints_prevent_duplicates():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    expense_category = category_id(client, "expense")
    month = tenant_today().replace(day=1).isoformat()
    budget_payload = {
        "category_id": expense_category,
        "competence_month": month,
        "limit_amount": "500.00",
    }
    assert client.post("/api/v1/budgets", json=budget_payload).status_code == 201
    assert client.post("/api/v1/budgets", json=budget_payload).status_code == 409
    assert count(Budget, tenant_id) == 1

    bill = client.post(
        "/api/v1/bills",
        json={
            "name": "Recorrente",
            "amount": "10.00",
            "due_on": tenant_today().isoformat(),
            "recurrence": "monthly",
        },
    ).json()
    first = client.post(f"/api/v1/bills/{bill['id']}/recurrence")
    second = client.post(f"/api/v1/bills/{bill['id']}/recurrence")
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert count(Bill, tenant_id) == 2


def test_concurrent_recurrence_creates_one_occurrence():
    tenant_id, _, token, _ = create_tenant_user()
    client = client_for(token)
    bill = client.post(
        "/api/v1/bills",
        json={
            "name": "Recorrência concorrente",
            "amount": "10.00",
            "due_on": tenant_today().isoformat(),
            "recurrence": "monthly",
        },
    ).json()

    def recur():
        return client_for(token).post(f"/api/v1/bills/{bill['id']}/recurrence").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: recur(), range(2)))

    assert statuses == [201, 201]
    assert count(Bill, tenant_id) == 2
