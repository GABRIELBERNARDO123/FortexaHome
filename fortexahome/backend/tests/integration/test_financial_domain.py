from __future__ import annotations

import csv
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import email_lookup_hash, encrypt_text, license_code_hash, masked_email
from app.core.security import hash_password
from app.main import app
from app.models.category import Category
from app.models.license import License
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.user import User
from app.services import auth_service, license_service

pytestmark = pytest.mark.integration
settings = get_settings()
PASSWORD = "SenhaSegura#2026"


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.test"


def create_product() -> uuid.UUID:
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        product = Product(
            slug=f"finance-{uuid.uuid4().hex[:12]}",
            name="Produto financeiro",
            price_cents=19990,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.commit()
        return product.id


def create_tenant_user(email: str | None = None, *, role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, str, uuid.UUID]:
    email = email or unique_email(role)
    tenant_id = uuid.uuid4()
    product_id = create_product()
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Família teste", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        user = User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(email, "users.email"),
            email_lookup_hash=email_lookup_hash(email),
            email_masked=masked_email(email),
            name_encrypted=encrypt_text("Pessoa Teste", "users.name"),
            password_hash=hash_password(PASSWORD),
            role=role,
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        product = db.get(Product, product_id)
        code = f"FH-FIN-{uuid.uuid4().hex[:16].upper()}"
        set_db_context(db, catalog_write="true", license_code_hash=license_code_hash(code))
        license_row, _ = license_service.issue_license(db, product, code=code, buyer_email=email)
        set_db_context(db, tenant_id=tenant_id, license_code_hash=license_code_hash(code))
        license_service.bind_license(db, license_row, tenant_id, email_lookup_hash(email))
        auth_service._seed_categories(db, tenant_id)
        token, _ = auth_service._create_session(db, user)
        db.commit()
        return tenant_id, user.id, token, product_id


def add_member(tenant_id: uuid.UUID, email: str | None = None) -> tuple[uuid.UUID, str]:
    email = email or unique_email("member")
    with SessionLocal() as db:
        set_db_context(db, tenant_id=tenant_id)
        user = User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(email, "users.email"),
            email_lookup_hash=email_lookup_hash(email),
            email_masked=masked_email(email),
            name_encrypted=encrypt_text("Membro Teste", "users.name"),
            password_hash=hash_password(PASSWORD),
            role="member",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        token, _ = auth_service._create_session(db, user)
        db.commit()
        return user.id, token


def client_for(token: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(settings.SESSION_COOKIE_NAME, token, path="/")
    return client


def categories(client: TestClient, kind: str) -> list[dict]:
    response = client.get(f"/api/v1/categories?kind={kind}")
    assert response.status_code == 200, response.text
    return response.json()


def category_id(client: TestClient, kind: str) -> str:
    return categories(client, kind)[0]["id"]


def tenant_today() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def month() -> str:
    return tenant_today().strftime("%Y-%m")


def test_transaction_crud_filters_summary_and_validation():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    expense_category = category_id(client, "expense")
    income_category = category_id(client, "income")
    today = tenant_today().isoformat()

    income = client.post(
        "/api/v1/transactions",
        json={
            "kind": "income",
            "amount": "1234.56",
            "occurred_on": today,
            "description": "Salário teste",
            "category_id": income_category,
            "payment_method": "pix",
        },
    )
    assert income.status_code == 201, income.text
    expense = client.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "200.10",
            "occurred_on": today,
            "description": "Mercado teste",
            "category_id": expense_category,
            "payment_method": "debit",
            "notes": "Compra semanal",
        },
    )
    assert expense.status_code == 201, expense.text
    expense_id = expense.json()["id"]

    summary = client.get(f"/api/v1/transactions/summary?start={today}&end={today}")
    assert summary.status_code == 200
    assert summary.json() == {"income": "1234.56", "expense": "200.10", "result": "1034.46", "count": 2}

    filtered = client.get("/api/v1/transactions?kind=expense&search=Mercado")
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1 and filtered.json()[0]["description"] == "Mercado teste"
    assert client.get("/api/v1/transactions?page_size=1&page=2").status_code == 200

    updated = client.patch(f"/api/v1/transactions/{expense_id}", json={"amount": "250.00", "notes": "Atualizado"})
    assert updated.status_code == 200
    assert updated.json()["amount"] == "250.00"
    assert updated.json()["notes"] == "Atualizado"

    assert client.delete(f"/api/v1/transactions/{expense_id}").status_code == 204
    assert client.post(
        "/api/v1/transactions",
        json={"kind": "expense", "amount": "-1", "occurred_on": today, "description": "Inválido"},
    ).status_code == 422
    assert client.post(
        "/api/v1/transactions",
        json={
            "kind": "income",
            "amount": "10.00",
            "occurred_on": today,
            "description": "Categoria errada",
            "category_id": expense_category,
        },
    ).status_code == 400
    assert client.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "10.00",
            "occurred_on": today,
            "description": "Cartão errado",
            "card_id": str(uuid.uuid4()),
            "payment_method": "pix",
        },
    ).status_code == 422


def test_bills_payment_unpay_recurrence_and_restrictions():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    due = tenant_today().replace(day=15).isoformat()
    created = client.post(
        "/api/v1/bills",
        json={"name": "Aluguel E2E", "amount": "1500.00", "due_on": due, "recurrence": "monthly"},
    )
    assert created.status_code == 201, created.text
    bill = created.json()
    assert client.post(
        "/api/v1/bills",
        json={"name": "Energia", "amount": "250.00", "due_on": due, "recurrence": "none"},
    ).status_code == 201

    paid = client.post(f"/api/v1/bills/{bill['id']}/pay")
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert paid.json()["transaction_id"]
    summary = client.get(f"/api/v1/transactions/summary?start={tenant_today().isoformat()}&end={tenant_today().isoformat()}")
    assert summary.json()["expense"] == "1500.00"
    assert client.post(f"/api/v1/bills/{bill['id']}/pay").status_code == 409
    assert client.patch(f"/api/v1/bills/{bill['id']}", json={"amount": "1600.00"}).status_code == 409

    unpay = client.post(f"/api/v1/bills/{bill['id']}/unpay")
    assert unpay.status_code == 200 and unpay.json()["status"] == "pending"
    summary = client.get(f"/api/v1/transactions/summary?start={tenant_today().isoformat()}&end={tenant_today().isoformat()}")
    assert summary.json()["expense"] == "0.00"

    next_bill = client.post(f"/api/v1/bills/{bill['id']}/recurrence")
    assert next_bill.status_code == 201
    assert next_bill.json()["due_on"] > due
    assert client.post(f"/api/v1/bills/{bill['id']}/recurrence").status_code == 201


def test_cards_spending_availability_and_archive():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    card = client.post(
        "/api/v1/cards",
        json={"name": "Cartão E2E", "institution": "Banco E2E", "limit_amount": "1000.00", "closing_day": 10, "due_day": 20},
    )
    assert card.status_code == 201, card.text
    card_id_value = card.json()["id"]
    expense = client.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "250.00",
            "occurred_on": tenant_today().isoformat(),
            "description": "Compra cartão",
            "payment_method": "credit",
            "card_id": card_id_value,
        },
    )
    assert expense.status_code == 201, expense.text
    listed = client.get("/api/v1/cards")
    assert listed.status_code == 200
    item = next(row for row in listed.json() if row["id"] == card_id_value)
    assert item["spent"] == "250.00" and item["available"] == "750.00"
    assert client.delete(f"/api/v1/cards/{card_id_value}").status_code == 204
    assert all(row["id"] != card_id_value for row in client.get("/api/v1/cards").json())
    assert any(row["id"] == card_id_value for row in client.get("/api/v1/cards?include_archived=true").json())


def test_budgets_spending_duplicate_and_validation():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    expense_category = category_id(client, "expense")
    income_category = category_id(client, "income")
    competence = f"{month()}-01"
    created = client.post(
        "/api/v1/budgets",
        json={"category_id": expense_category, "competence_month": competence, "limit_amount": "500.00"},
    )
    assert created.status_code == 201, created.text
    budget_id = created.json()["id"]
    assert client.post(
        "/api/v1/budgets",
        json={"category_id": expense_category, "competence_month": competence, "limit_amount": "600.00"},
    ).status_code == 409
    assert client.post(
        "/api/v1/budgets",
        json={"category_id": income_category, "competence_month": competence, "limit_amount": "100.00"},
    ).status_code == 400
    for amount in ("200.00", "100.00"):
        assert client.post(
            "/api/v1/transactions",
            json={"kind": "expense", "amount": amount, "occurred_on": tenant_today().isoformat(), "description": "Consumo orçamento", "category_id": expense_category},
        ).status_code == 201
    listed = client.get(f"/api/v1/budgets?month={month()}")
    assert listed.status_code == 200
    budget = next(row for row in listed.json() if row["id"] == budget_id)
    assert budget["spent"] == "300.00" and budget["available"] == "200.00" and budget["percent"] == 60.0
    updated = client.patch(f"/api/v1/budgets/{budget_id}", json={"limit_amount": "400.00"})
    assert updated.status_code == 200 and updated.json()["limit_amount"] == "400.00"
    assert client.delete(f"/api/v1/budgets/{budget_id}").status_code == 204


def test_goals_movements_completion_and_limits():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    target = (tenant_today() + timedelta(days=180)).isoformat()
    created = client.post(
        "/api/v1/goals",
        json={"name": "Reserva E2E", "target_amount": "1000.00", "target_date": target, "icon": "🎯"},
    )
    assert created.status_code == 201, created.text
    goal_id = created.json()["id"]
    deposit = client.post(f"/api/v1/goals/{goal_id}/movements", json={"kind": "deposit", "amount": "400.00", "occurred_on": tenant_today().isoformat()})
    assert deposit.status_code == 201
    assert deposit.json()["goal"]["saved_amount"] == "400.00"
    assert deposit.json()["goal"]["remaining_amount"] == "600.00"
    withdrawal = client.post(f"/api/v1/goals/{goal_id}/movements", json={"kind": "withdrawal", "amount": "100.00", "occurred_on": tenant_today().isoformat()})
    assert withdrawal.status_code == 201 and withdrawal.json()["goal"]["saved_amount"] == "300.00"
    assert client.post(f"/api/v1/goals/{goal_id}/movements", json={"kind": "withdrawal", "amount": "301.00"}).status_code == 400
    completed = client.post(f"/api/v1/goals/{goal_id}/movements", json={"kind": "deposit", "amount": "700.00"})
    assert completed.status_code == 201 and completed.json()["goal"]["status"] == "completed"
    reopened = client.post(f"/api/v1/goals/{goal_id}/movements", json={"kind": "withdrawal", "amount": "50.00"})
    assert reopened.status_code == 201 and reopened.json()["goal"]["status"] == "active"
    history = client.get(f"/api/v1/goals/{goal_id}/movements")
    assert history.status_code == 200 and len(history.json()) == 4
    updated = client.patch(f"/api/v1/goals/{goal_id}", json={"name": "Reserva atualizada"})
    assert updated.status_code == 200 and updated.json()["name"] == "Reserva atualizada"
    assert client.delete(f"/api/v1/goals/{goal_id}").status_code == 204


def test_dashboard_reports_and_csv():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    income_category = category_id(client, "income")
    expense_category = category_id(client, "expense")
    today = tenant_today().isoformat()
    assert client.post("/api/v1/transactions", json={"kind": "income", "amount": "1000.00", "occurred_on": today, "description": "Receita relatório", "category_id": income_category}).status_code == 201
    assert client.post("/api/v1/transactions", json={"kind": "expense", "amount": "250.00", "occurred_on": today, "description": "Despesa relatório", "category_id": expense_category}).status_code == 201
    dashboard = client.get(f"/api/v1/dashboard?month={month()}")
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["income"] == "1000.00" and body["expense"] == "250.00" and body["result"] == "750.00"
    assert body["total_balance"] == "750.00"
    report = client.get(f"/api/v1/reports/monthly?month={month()}")
    assert report.status_code == 200
    assert report.json()["income"] == "1000.00" and report.json()["expense"] == "250.00"
    csv_response = client.get(f"/api/v1/reports/transactions.csv?start={today}&end={today}")
    assert csv_response.status_code == 200
    text = csv_response.text
    assert "Receita relatório" in text and "Despesa relatório" in text and "1000.00" in text
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
    assert len(rows) == 3


def test_account_update_export_and_owner_member_permissions():
    _, _, token, _ = create_tenant_user()
    owner = client_for(token)
    assert owner.patch("/api/v1/account", json={"family_name": "Família Atualizada", "timezone": "America/Manaus"}).status_code == 200
    assert owner.patch("/api/v1/account", json={"timezone": "Fuso/Invalido"}).status_code == 400
    today = tenant_today().isoformat()
    owner.post("/api/v1/transactions", json={"kind": "expense", "amount": "10.00", "occurred_on": today, "description": "Exportar"})
    exported = owner.get("/api/v1/account/export")
    assert exported.status_code == 200 and len(exported.json()["transactions"]) == 1
    tenant_id = uuid.UUID(owner.get("/api/v1/auth/me").json()["tenant"]["id"])
    _, member_token = add_member(tenant_id)
    member = client_for(member_token)
    assert member.patch("/api/v1/account", json={"family_name": "Tentativa"}).status_code == 403
    assert member.patch("/api/v1/account", json={"name": "Membro Atualizado"}).status_code == 200
    assert member.post("/api/v1/categories", json={"name": "Nova", "kind": "expense"}).status_code == 403


def test_tenant_isolation_via_api_for_financial_records():
    _, _, token_a, _ = create_tenant_user()
    _, _, token_b, _ = create_tenant_user()
    client_a, client_b = client_for(token_a), client_for(token_b)
    today = tenant_today().isoformat()
    created = client_a.post("/api/v1/transactions", json={"kind": "expense", "amount": "99.99", "occurred_on": today, "description": "Somente A"})
    assert created.status_code == 201
    transaction_id = created.json()["id"]
    assert client_b.get("/api/v1/transactions").json() == []
    assert client_b.patch(f"/api/v1/transactions/{transaction_id}", json={"amount": "1.00"}).status_code == 404
    assert client_b.delete(f"/api/v1/transactions/{transaction_id}").status_code == 404
    bill = client_a.post("/api/v1/bills", json={"name": "Conta A", "amount": "50.00", "due_on": today}).json()
    assert client_b.post(f"/api/v1/bills/{bill['id']}/pay").status_code == 404
    goal = client_a.post("/api/v1/goals", json={"name": "Meta A", "target_amount": "100.00"}).json()
    assert client_b.get(f"/api/v1/goals/{goal['id']}/movements").status_code == 404


def test_concurrent_goal_withdrawals_cannot_overdraw():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    goal = client.post("/api/v1/goals", json={"name": "Corrida meta", "target_amount": "1000.00"}).json()
    assert client.post(f"/api/v1/goals/{goal['id']}/movements", json={"kind": "deposit", "amount": "100.00"}).status_code == 201

    def withdraw():
        local_client = client_for(token)
        return local_client.post(
            f"/api/v1/goals/{goal['id']}/movements",
            json={"kind": "withdrawal", "amount": "80.00"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: withdraw(), range(2)))
    assert sorted(statuses) == [201, 400]
    goal_state = client.get("/api/v1/goals").json()[0]
    assert float(goal_state["saved_amount"]) == 20.0


def test_concurrent_bill_payment_creates_only_one_transaction():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    bill = client.post(
        "/api/v1/bills",
        json={"name": "Conta corrida", "amount": "77.77", "due_on": tenant_today().isoformat()},
    ).json()

    def pay():
        return client_for(token).post(f"/api/v1/bills/{bill['id']}/pay").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: pay(), range(2)))
    assert sorted(statuses) == [200, 409]
    transactions = client.get("/api/v1/transactions?search=Conta corrida").json()
    assert len(transactions) == 1
    assert transactions[0]["source"] == "bill"


def test_category_management_owner_member_usage_and_archive():
    tenant_id, _, token, _ = create_tenant_user()
    owner = client_for(token)
    listed = owner.get("/api/v1/categories")
    assert listed.status_code == 200
    assert len(listed.json()) == 14
    assert all(item["archived"] is False and item["usage_count"] == 0 and item["in_use"] is False for item in listed.json())
    system_category = next(item for item in listed.json() if item["is_system"])

    created = owner.post(
        "/api/v1/categories",
        json={"name": "Categoria pessoal", "kind": "expense", "color": "#123ABC", "icon": "paw"},
    )
    assert created.status_code == 201, created.text
    category = created.json()
    assert category["archived"] is False and category["usage_count"] == 0 and category["is_system"] is False
    assert owner.post(
        "/api/v1/categories",
        json={"name": "  categoria PESSOAL ", "kind": "expense"},
    ).status_code == 409

    _, member_token = add_member(tenant_id)
    member = client_for(member_token)
    assert any(item["id"] == category["id"] for item in member.get("/api/v1/categories").json())
    assert member.patch(f"/api/v1/categories/{category['id']}", json={"archived": True}).status_code == 403
    assert member.delete(f"/api/v1/categories/{category['id']}").status_code == 403

    updated = owner.patch(
        f"/api/v1/categories/{category['id']}",
        json={"name": "Categoria pessoal editada", "color": "#00AA55", "icon": "heart"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Categoria pessoal editada"
    assert updated.json()["color"] == "#00AA55"

    today = tenant_today().isoformat()
    transaction = owner.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "42.00",
            "occurred_on": today,
            "description": "Compra da categoria pessoal",
            "category_id": category["id"],
        },
    )
    assert transaction.status_code == 201, transaction.text
    usage = next(item for item in owner.get("/api/v1/categories").json() if item["id"] == category["id"])
    assert usage["usage_count"] == 1 and usage["in_use"] is True

    archived = owner.patch(f"/api/v1/categories/{category['id']}", json={"archived": True})
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived"] is True and archived.json()["usage_count"] == 1
    assert any(
        item["id"] == category["id"]
        for item in owner.get("/api/v1/categories?archived=true").json()
    )
    assert all(
        item["id"] != category["id"]
        for item in owner.get("/api/v1/categories?archived=false").json()
    )

    assert owner.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "10.00",
            "occurred_on": today,
            "description": "Tentativa categoria arquivada",
            "category_id": category["id"],
        },
    ).status_code == 400
    assert owner.post(
        "/api/v1/bills",
        json={"name": "Conta arquivada", "amount": "10.00", "due_on": today, "category_id": category["id"]},
    ).status_code == 400
    assert owner.post(
        "/api/v1/budgets",
        json={"category_id": category["id"], "competence_month": f"{month()}-01", "limit_amount": "10.00"},
    ).status_code == 400

    kept = owner.patch(
        f"/api/v1/transactions/{transaction.json()['id']}",
        json={"description": "Histórico preservado", "category_id": category["id"]},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["category_name"] == "Categoria pessoal editada"

    active = owner.post("/api/v1/categories", json={"name": "Categoria ativa", "kind": "expense"}).json()
    second = owner.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "20.00",
            "occurred_on": today,
            "description": "Troca para arquivada",
            "category_id": active["id"],
        },
    ).json()
    assert owner.patch(
        f"/api/v1/transactions/{second['id']}",
        json={"category_id": category["id"]},
    ).status_code == 400

    assert owner.delete(f"/api/v1/categories/{category['id']}").status_code == 409
    assert owner.patch(f"/api/v1/categories/{system_category['id']}", json={"archived": True}).status_code == 409
    assert owner.delete(f"/api/v1/categories/{system_category['id']}").status_code == 409

    reactivated = owner.patch(f"/api/v1/categories/{category['id']}", json={"archived": False})
    assert reactivated.status_code == 200 and reactivated.json()["archived"] is False
    assert owner.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "5.00",
            "occurred_on": today,
            "description": "Categoria reativada",
            "category_id": category["id"],
        },
    ).status_code == 201

    unused = owner.post("/api/v1/categories", json={"name": "Categoria sem uso", "kind": "income"}).json()
    assert owner.delete(f"/api/v1/categories/{unused['id']}").status_code == 204

    _, _, other_token, _ = create_tenant_user()
    other = client_for(other_token)
    assert all(item["id"] != category["id"] for item in other.get("/api/v1/categories").json())
    assert other.patch(f"/api/v1/categories/{category['id']}", json={"name": "Invasão"}).status_code == 404
    assert other.delete(f"/api/v1/categories/{category['id']}").status_code == 404
    assert other.post(
        "/api/v1/transactions",
        json={
            "kind": "expense",
            "amount": "10.00",
            "occurred_on": today,
            "description": "Categoria de outro tenant",
            "category_id": category["id"],
        },
    ).status_code == 404


def test_archived_category_preserves_bill_budget_and_recurrence_history():
    _, _, token, _ = create_tenant_user()
    client = client_for(token)
    category = client.post(
        "/api/v1/categories",
        json={"name": "Categoria histórica", "kind": "expense"},
    ).json()
    bill = client.post(
        "/api/v1/bills",
        json={
            "name": "Conta histórica",
            "amount": "55.00",
            "due_on": tenant_today().isoformat(),
            "category_id": category["id"],
            "recurrence": "monthly",
        },
    )
    assert bill.status_code == 201, bill.text
    budget = client.post(
        "/api/v1/budgets",
        json={"category_id": category["id"], "competence_month": f"{month()}-01", "limit_amount": "200.00"},
    )
    assert budget.status_code == 201, budget.text
    assert client.patch(f"/api/v1/categories/{category['id']}", json={"archived": True}).status_code == 200

    listed_bill = next(
        item for item in client.get(f"/api/v1/bills?start={tenant_today().isoformat()}&end={tenant_today().isoformat()}").json()
        if item["id"] == bill.json()["id"]
    )
    assert listed_bill["category_name"] == "Categoria histórica"
    assert any(
        item["id"] == budget.json()["id"]
        for item in client.get(f"/api/v1/budgets?month={month()}").json()
    )

    paid = client.post(f"/api/v1/bills/{bill.json()['id']}/pay")
    assert paid.status_code == 200, paid.text
    assert paid.json()["category_name"] == "Categoria histórica"
    generated = client.post(f"/api/v1/bills/{bill.json()['id']}/recurrence")
    assert generated.status_code == 201, generated.text
    assert generated.json()["category_id"] == category["id"]
    transactions = client.get("/api/v1/transactions?search=Conta histórica").json()
    assert len(transactions) == 1
    assert transactions[0]["category_name"] == "Categoria histórica"
