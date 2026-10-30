from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import set_db_context
from app.core.field_encryption import (
    email_lookup_hash,
    encrypt_text,
    generate_license_code,
    license_code_hash,
    license_code_last4,
)
from app.integrations.payments.base import PaymentNotification
from app.models.license import License
from app.models.order import Order
from app.models.payment_event import PaymentEvent
from app.models.product import Product
from app.models.session import UserSession
from app.services import audit_service, email_service

settings = get_settings()


def get_product_by_slug(db: Session, slug: str) -> Product | None:
    return db.scalar(select(Product).where(Product.slug == slug))


def get_license_by_code(db: Session, code: str) -> License | None:
    code_hash = license_code_hash(code)
    set_db_context(db, license_code_hash=code_hash)
    return db.scalar(select(License).where(License.code_hash == code_hash))


def get_license_for_tenant(db: Session, tenant_id: uuid.UUID) -> License | None:
    return db.scalar(select(License).where(License.tenant_id == tenant_id))


def issue_license(
    db: Session,
    product: Product,
    *,
    order_id: uuid.UUID | None = None,
    code: str | None = None,
    buyer_email: str | None = None,
) -> tuple[License, str]:
    plain_code = code or generate_license_code()
    set_db_context(db, license_code_hash=license_code_hash(plain_code))
    license_row = License(
        product_id=product.id,
        order_id=order_id,
        code_hash=license_code_hash(plain_code),
        code_last4=license_code_last4(plain_code),
        status="pending",
        bound_email_hash=email_lookup_hash(buyer_email) if buyer_email else None,
    )
    db.add(license_row)
    db.flush()
    return license_row, plain_code


def validate_license_for_activation(
    db: Session, code: str, *, email_hash: str | None = None
) -> License:
    code_hash = license_code_hash(code)
    set_db_context(db, license_code_hash=code_hash)
    license_row = db.scalar(
        select(License).where(License.code_hash == code_hash).with_for_update()
    )
    if license_row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código de licença inválido")
    if license_row.tenant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta licença já foi vinculada a uma conta. Entre com o e-mail cadastrado.",
        )
    if license_row.status in {"cancelled", "suspended"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Licença revogada ou suspensa")
    if license_row.status == "expired" or (
        license_row.expires_at is not None and license_row.expires_at <= datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Licença expirada")
    if license_row.status not in {"pending", "active"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Licença indisponível para ativação")
    if (
        email_hash is not None
        and license_row.bound_email_hash is not None
        and license_row.bound_email_hash != email_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta licença está vinculada a outro e-mail.",
        )
    return license_row


def bind_license(db: Session, license_row: License, tenant_id: uuid.UUID, buyer_email_hash: str) -> None:
    license_row.tenant_id = tenant_id
    license_row.status = "active"
    license_row.activated_at = datetime.now(timezone.utc)
    license_row.bound_email_hash = buyer_email_hash
    db.flush()


def revoke_tenant_sessions(db: Session, tenant_id: uuid.UUID) -> None:
    set_db_context(db, tenant_id=tenant_id)
    db.execute(
        update(UserSession)
        .where(UserSession.tenant_id == tenant_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


def seed_demo(db: Session) -> dict:
    if settings.is_production:
        raise RuntimeError("Não é permitido criar licença de demonstração em produção")
    product = get_product_by_slug(db, settings.DEMO_PRODUCT_SLUG)
    if product is None:
        product = Product(
            slug=settings.DEMO_PRODUCT_SLUG,
            name="FortexaHome — Licença vitalícia (demonstração)",
            description="Licença exclusiva para desenvolvimento local.",
            price_cents=settings.DEMO_PRODUCT_PRICE_CENTS,
            currency="BRL",
            license_kind="lifetime",
            active=True,
        )
        db.add(product)
        db.flush()

    demo_code = settings.DEMO_LICENSE_CODE
    existing = get_license_by_code(db, demo_code)
    created = False
    if existing is None:
        issue_license(db, product, code=demo_code)
        created = True
    db.commit()
    return {"product": product.slug, "code": demo_code, "created": created}


def _find_order(db: Session, provider: str, external_order_id: str) -> Order | None:
    return db.scalar(
        select(Order).where(Order.provider == provider, Order.external_order_id == external_order_id)
    )


def process_payment_notification(
    db: Session, notification: PaymentNotification, *, provider: str, payload_hash: str
) -> dict:
    existing_event = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider == provider,
            PaymentEvent.external_event_id == notification.event_id,
        )
    )
    if existing_event is not None:
        return {"status": "duplicate"}

    order = _find_order(db, provider, notification.external_order_id) if notification.external_order_id else None
    released_code: str | None = None

    if notification.event_type == "payment.paid":
        if not notification.external_order_id or not notification.product_slug or not notification.buyer_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Notificação de pagamento incompleta")
        product = get_product_by_slug(db, notification.product_slug)
        if product is None or not product.active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Produto não encontrado")

        if order is None:
            order = Order(
                provider=provider,
                external_order_id=notification.external_order_id,
                product_id=product.id,
                buyer_email_encrypted=encrypt_text(notification.buyer_email, "orders.buyer_email"),
                buyer_email_hash=email_lookup_hash(notification.buyer_email),
                amount_cents=notification.amount_cents,
                currency=notification.currency,
                status="paid",
                external_customer_id=notification.customer_id,
            )
            db.add(order)
            db.flush()
        else:
            order.status = "paid"
            order.amount_cents = notification.amount_cents
            order.currency = notification.currency

        license_row = db.scalar(select(License).where(License.order_id == order.id))
        if license_row is None:
            license_row, released_code = issue_license(
                db, product, order_id=order.id, buyer_email=notification.buyer_email
            )
            email_service.send_license_delivery(notification.buyer_email, released_code, product.name)

    elif notification.event_type in {"payment.refunded", "payment.chargeback", "payment.cancelled"}:
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado")
        order.status = {
            "payment.refunded": "refunded",
            "payment.chargeback": "chargeback",
            "payment.cancelled": "cancelled",
        }[notification.event_type]
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        if license_row is not None:
            license_row.status = "suspended" if notification.event_type == "payment.chargeback" else "cancelled"
            license_row.revoked_at = datetime.now(timezone.utc)
            if license_row.tenant_id is not None:
                revoke_tenant_sessions(db, license_row.tenant_id)

    event_row = PaymentEvent(
        provider=provider,
        external_event_id=notification.event_id,
        event_type=notification.event_type,
        order_id=order.id if order else None,
        payload_hash=payload_hash,
    )
    db.add(event_row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate"}

    return {
        "status": "processed",
        "license_code": released_code if settings.DEBUG else None,
    }
