"""Seed exclusivo do ambiente E2E descartável. Nunca execute fora de ENV=test."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.database import SessionLocal, set_db_context
from app.core.email_verification import verification_code_hash
from app.core.field_encryption import (
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
from app.models.payment_event import PaymentEvent
from app.models.pending_activation import PendingActivation
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.user import User
from app.services import auth_service, email_outbox_service, license_service, support_service

settings = get_settings()

if settings.ENV != "test" or os.environ.get("E2E_SEED") != "1":
    raise SystemExit("Seed E2E bloqueado: requer ENV=test e E2E_SEED=1")

PASSWORD = "E2eSenha#2026"
ACTIVATION_NAME = "Cliente Ativação"
ACTIVATION_EMAIL = "ativacao.e2e@example.com"
ACTIVATION_CODE = "FH-E2E-ATIV-0001"
ACTIVATION_CHALLENGE_CODE = "123456"
RECOVERY_NAME = "Cliente Recuperação"
RECOVERY_EMAIL = "recuperacao.e2e@example.com"
RECOVERY_CODE = "FH-E2E-REC-0001"
RECOVERY_CHALLENGE_CODE = "654321"
CUSTOMER_EMAIL = "cliente.e2e@example.com"
MEMBER_EMAIL = "membro.e2e@example.com"
CUSTOMER2_EMAIL = "cliente2.e2e@example.com"
PRIVACY_OWNER_EMAIL = "privacidade.owner.e2e@example.com"
PRIVACY_MEMBER_EMAIL = "privacidade.member.e2e@example.com"
SUPPORT_EMAIL = "suporte.e2e@example.com"
SUPPORT_PASSWORD = "SuporteE2e#2026"
READ_ONLY_EMAIL = "leitura.e2e@example.com"
LOCKOUT_EMAIL = "lockout.e2e@example.com"


def _product(db) -> Product:
    set_db_context(db, catalog_write="true")
    product = Product(
        slug="fortexahome-e2e",
        name="FortexaHome E2E",
        description="Produto isolado do ambiente E2E",
        price_cents=19990,
        currency="BRL",
        license_kind="lifetime",
        active=True,
    )
    db.add(product)
    db.flush()
    return product


def _paid_order(db, *, transaction: str, product: Product, email: str, status: str = "paid") -> Order:
    set_db_context(db, payment_provider="hotmart")
    order = Order(
        provider="hotmart",
        external_order_id=transaction,
        product_id=product.id,
        buyer_email_encrypted=encrypt_text(email, "orders.buyer_email"),
        buyer_email_hash=email_lookup_hash(email),
        amount_cents=product.price_cents,
        currency=product.currency,
        status=status,
    )
    db.add(order)
    db.flush()
    return order


def _license_for(
    db,
    *,
    product: Product,
    order: Order | None,
    code: str,
    email: str,
    status: str = "pending",
) -> License:
    set_db_context(db, payment_provider="hotmart", license_code_hash=license_code_hash(code))
    license_row = License(
        product_id=product.id,
        order_id=order.id if order else None,
        code_hash=license_code_hash(code),
        code_last4=license_code_last4(code),
        status=status,
        bound_email_hash=email_lookup_hash(email),
    )
    db.add(license_row)
    db.flush()
    return license_row


def _pending_activation(
    db,
    *,
    license_row: License,
    name: str,
    email: str,
    code: str,
) -> PendingActivation:
    activation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    set_db_context(db, pending_activation_id=activation_id)
    activation = PendingActivation(
        id=activation_id,
        license_id=license_row.id,
        license_code_hash=license_row.code_hash,
        email_encrypted=encrypt_text(email, "pending_activations.email"),
        email_lookup_hash=email_lookup_hash(email),
        name_encrypted=encrypt_text(name, "pending_activations.name"),
        password_hash=hash_password(PASSWORD),
        verification_code_hash=verification_code_hash(activation_id, code),
        expires_at=now + timedelta(minutes=10),
        last_sent_at=now,
        attempt_count=0,
        status="pending",
    )
    db.add(activation)
    db.flush()
    return activation


def seed() -> None:
    with SessionLocal() as db:
        product = _product(db)

        # Ativação: licença paga não ativada + desafio conhecido.
        activation_order = _paid_order(
            db, transaction="TX-E2E-ACTV-0001", product=product, email=ACTIVATION_EMAIL
        )
        activation_license = _license_for(
            db, product=product, order=activation_order, code=ACTIVATION_CODE, email=ACTIVATION_EMAIL
        )
        _pending_activation(
            db,
            license_row=activation_license,
            name=ACTIVATION_NAME,
            email=ACTIVATION_EMAIL,
            code=ACTIVATION_CHALLENGE_CODE,
        )

        # Recuperação: licença paga não ativada + desafio conhecido.
        recovery_order = _paid_order(
            db, transaction="TX-E2E-REC-0001", product=product, email=RECOVERY_EMAIL
        )
        recovery_license = _license_for(
            db, product=product, order=recovery_order, code=RECOVERY_CODE, email=RECOVERY_EMAIL
        )
        _pending_activation(
            db,
            license_row=recovery_license,
            name=RECOVERY_NAME,
            email=RECOVERY_EMAIL,
            code=RECOVERY_CHALLENGE_CODE,
        )

        # Conta do cliente para login e CRUD financeiro.
        tenant_id = uuid.uuid4()
        set_db_context(db, tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name="Família E2E", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        customer = User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(CUSTOMER_EMAIL, "users.email"),
            email_lookup_hash=email_lookup_hash(CUSTOMER_EMAIL),
            email_masked=masked_email(CUSTOMER_EMAIL),
            name_encrypted=encrypt_text("Cliente E2E", "users.name"),
            password_hash=hash_password(PASSWORD),
            role="owner",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(customer)
        member = User(
            tenant_id=tenant_id,
            email_encrypted=encrypt_text(MEMBER_EMAIL, "users.email"),
            email_lookup_hash=email_lookup_hash(MEMBER_EMAIL),
            email_masked=masked_email(MEMBER_EMAIL),
            name_encrypted=encrypt_text("Membro E2E", "users.name"),
            password_hash=hash_password(PASSWORD),
            role="member",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(member)
        db.flush()
        auth_service._seed_categories(db, tenant_id)
        set_db_context(db, tenant_id=tenant_id, payment_provider="", license_code_hash=license_code_hash("FH-E2E-CLI-0001"))
        customer_license, _ = license_service.issue_license(
            db, product, code="FH-E2E-CLI-0001", buyer_email=CUSTOMER_EMAIL
        )
        license_service.bind_license(db, customer_license, tenant_id, email_lookup_hash(CUSTOMER_EMAIL))

        # Segundo tenant para validar isolamento de categorias e dados financeiros.
        tenant2_id = uuid.uuid4()
        set_db_context(db, tenant_id=tenant2_id)
        db.add(Tenant(id=tenant2_id, name="Família E2E 2", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        customer2 = User(
            tenant_id=tenant2_id,
            email_encrypted=encrypt_text(CUSTOMER2_EMAIL, "users.email"),
            email_lookup_hash=email_lookup_hash(CUSTOMER2_EMAIL),
            email_masked=masked_email(CUSTOMER2_EMAIL),
            name_encrypted=encrypt_text("Cliente E2E 2", "users.name"),
            password_hash=hash_password(PASSWORD),
            role="owner",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(customer2)
        db.flush()
        auth_service._seed_categories(db, tenant2_id)
        set_db_context(
            db,
            tenant_id=tenant2_id,
            payment_provider="",
            license_code_hash=license_code_hash("FH-E2E-CLI-0002"),
        )
        customer2_license, _ = license_service.issue_license(
            db, product, code="FH-E2E-CLI-0002", buyer_email=CUSTOMER2_EMAIL
        )
        license_service.bind_license(db, customer2_license, tenant2_id, email_lookup_hash(CUSTOMER2_EMAIL))

        # Tenant dedicado à jornada de privacidade/LGPD.
        tenant3_id = uuid.uuid4()
        set_db_context(db, tenant_id=tenant3_id)
        db.add(Tenant(id=tenant3_id, name="Família Privacidade E2E", currency="BRL", timezone="America/Sao_Paulo"))
        db.flush()
        privacy_owner = User(
            tenant_id=tenant3_id,
            email_encrypted=encrypt_text(PRIVACY_OWNER_EMAIL, "users.email"),
            email_lookup_hash=email_lookup_hash(PRIVACY_OWNER_EMAIL),
            email_masked=masked_email(PRIVACY_OWNER_EMAIL),
            name_encrypted=encrypt_text("Responsável Privacidade E2E", "users.name"),
            password_hash=hash_password(PASSWORD),
            role="owner",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        privacy_member = User(
            tenant_id=tenant3_id,
            email_encrypted=encrypt_text(PRIVACY_MEMBER_EMAIL, "users.email"),
            email_lookup_hash=email_lookup_hash(PRIVACY_MEMBER_EMAIL),
            email_masked=masked_email(PRIVACY_MEMBER_EMAIL),
            name_encrypted=encrypt_text("Membro Privacidade E2E", "users.name"),
            password_hash=hash_password(PASSWORD),
            role="member",
            status="active",
            theme="claro",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(privacy_owner)
        db.add(privacy_member)
        db.flush()
        auth_service._seed_categories(db, tenant3_id)
        set_db_context(
            db,
            tenant_id=tenant3_id,
            payment_provider="",
            license_code_hash=license_code_hash("FH-E2E-PRIV-0001"),
        )
        privacy_license, _ = license_service.issue_license(
            db, product, code="FH-E2E-PRIV-0001", buyer_email=PRIVACY_OWNER_EMAIL
        )
        license_service.bind_license(db, privacy_license, tenant3_id, email_lookup_hash(PRIVACY_OWNER_EMAIL))

        # Pedido para consulta/ação do suporte.
        support_order = _paid_order(
            db, transaction="TX-E2E-0001", product=product, email="comprador.e2e@example.com"
        )
        support_license = _license_for(
            db,
            product=product,
            order=support_order,
            code="FH-E2E-SUP-0001",
            email="comprador.e2e@example.com",
        )
        db.add(
            PaymentEvent(
                provider="hotmart",
                external_event_id="evt-e2e-approved",
                event_type="PURCHASE_APPROVED",
                order_id=support_order.id,
                payload_hash="e" * 64,
                provider_event_created_at=datetime.now(timezone.utc),
                state_priority=2,
            )
        )
        set_db_context(db, outbox_license_id=support_license.id)
        email_outbox_service.enqueue_email(
            db,
            event_type="license_delivery",
            payload={"to": "comprador.e2e@example.com", "code": "FH-E2E-SUP-0001", "product_name": product.name},
            idempotency_key=f"e2e-license-delivery:{support_license.id}",
            aggregate_id=support_license.id,
        )

        # Pedido terminal para testar recusa do suporte.
        refunded_order = _paid_order(
            db,
            transaction="TX-E2E-REF-0001",
            product=product,
            email="reembolsado.e2e@example.com",
            status="refunded",
        )
        _license_for(
            db,
            product=product,
            order=refunded_order,
            code="FH-E2E-REF-0001",
            email="reembolsado.e2e@example.com",
            status="cancelled",
        )
        db.commit()

    for email, role in (
        (SUPPORT_EMAIL, "support_operator"),
        (READ_ONLY_EMAIL, "support_read"),
        (LOCKOUT_EMAIL, "support_read"),
    ):
        with SessionLocal() as db:
            support_service.provision_support_operator(
                db,
                email=email,
                name=email.split("@")[0],
                role=role,
                password=SUPPORT_PASSWORD,
                active=True,
                apply=True,
            )
            db.commit()

    print("E2E seed concluído")


if __name__ == "__main__":
    seed()
