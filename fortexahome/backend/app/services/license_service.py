from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException, status
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
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
from app.integrations.payments.hotmart import HotmartWebhookPayload, event_time, normalized_buyer_email
from app.models.license import License
from app.models.order import Order
from app.models.payment_event import PaymentEvent
from app.models.product import Product
from app.models.session import UserSession
from app.services import audit_service, email_outbox_service

settings = get_settings()


class CatalogProvisionError(Exception):
    """Base error for administrative catalog provisioning."""


class CatalogConflictError(CatalogProvisionError):
    """The requested slug conflicts with an existing catalog row."""


class CatalogPermissionError(CatalogProvisionError):
    """The database role cannot write the catalog under the current policies."""


@dataclass(frozen=True)
class ProductProvisionResult:
    action: str
    product: Product
    changed_fields: tuple[str, ...]


def get_product_by_slug(db: Session, slug: str) -> Product | None:
    return db.scalar(select(Product).where(Product.slug == slug))


def provision_product(
    db: Session,
    *,
    slug: str,
    name: str,
    price_cents: int,
    currency: str,
    license_kind: str,
    description: str | None = None,
    description_provided: bool = False,
    active: bool | None = None,
    apply: bool = True,
) -> ProductProvisionResult:
    """Create or update one product by slug using the existing catalog RLS context.

    The caller owns the final commit. In dry-run mode no row is inserted or mutated.
    An existing inactive product is never reactivated unless ``active=True`` is explicit.
    """
    from app.schemas.product import ProductProvision

    data = ProductProvision(
        slug=slug,
        name=name,
        description=description,
        price_cents=price_cents,
        currency=currency,
        license_kind=license_kind,
        active=active,
    )
    try:
        set_db_context(db, catalog_write="true")
        product = db.scalar(
            select(Product).where(Product.slug == data.slug).with_for_update()
        )
        if product is None:
            product = Product(
                slug=data.slug,
                name=data.name,
                description=data.description if description_provided else None,
                price_cents=data.price_cents,
                currency=data.currency,
                license_kind=data.license_kind,
                active=True if data.active is None else data.active,
            )
            fields = ("slug", "name", "description", "price_cents", "currency", "license_kind", "active")
            if not apply:
                return ProductProvisionResult("would_create", product, fields)
            db.add(product)
            db.flush()
            return ProductProvisionResult("created", product, fields)

        changes: dict[str, object] = {}
        for field in ("name", "price_cents", "currency", "license_kind"):
            value = getattr(data, field)
            if getattr(product, field) != value:
                changes[field] = value
        if description_provided and product.description != data.description:
            changes["description"] = data.description
        if data.active is not None and product.active != data.active:
            changes["active"] = data.active

        if not changes:
            return ProductProvisionResult("unchanged", product, ())
        if not apply:
            return ProductProvisionResult("would_update", product, tuple(sorted(changes)))

        for field, value in changes.items():
            setattr(product, field, value)
        db.flush()
        return ProductProvisionResult("updated", product, tuple(sorted(changes)))
    except IntegrityError as exc:
        raise CatalogConflictError("slug já existe no catálogo") from exc
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None)
        if sqlstate == "42501":
            raise CatalogPermissionError(
                "o papel do banco não pode gravar o catálogo com o contexto administrativo"
            ) from exc
        raise


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
    return _validate_activation_row(license_row, email_hash)


def validate_license_for_activation_hash(
    db: Session, license_id: uuid.UUID, code_hash: str, *, email_hash: str | None = None
) -> License:
    set_db_context(db, license_code_hash=code_hash)
    license_row = db.scalar(
        select(License)
        .where(License.id == license_id, License.code_hash == code_hash)
        .with_for_update()
    )
    return _validate_activation_row(license_row, email_hash)


def _validate_activation_row(license_row: License | None, email_hash: str | None) -> License:
    if license_row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ativação indisponível")
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
    set_db_context(db, catalog_write="true")
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
    set_db_context(db, payment_provider=provider)
    existing_event = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider == provider,
            PaymentEvent.external_event_id == notification.event_id,
        )
    )
    if existing_event is not None:
        return {"status": "duplicate"}

    order = _find_order(db, provider, notification.external_order_id) if notification.external_order_id else None
    if order is not None:
        set_db_context(db, payment_provider=provider, payment_order_id=order.id)
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

        set_db_context(db, payment_provider=provider, payment_order_id=order.id)
        license_row = db.scalar(select(License).where(License.order_id == order.id))
        if license_row is None:
            license_row, released_code = issue_license(
                db, product, order_id=order.id, buyer_email=notification.buyer_email
            )
            email_outbox_service.enqueue_email(
                db,
                event_type="license_delivery",
                payload={"to": notification.buyer_email, "code": released_code, "product_name": product.name},
                idempotency_key=f"license-delivery:{license_row.id}",
                aggregate_id=license_row.id,
            )

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


_TERMINAL_ORDER_STATUSES = frozenset({"refunded", "chargeback", "cancelled"})

_HOTMART_PRIORITY = {
    "PURCHASE_COMPLETE": 0,
    "PURCHASE_BILLET_PRINTED": 0,
    "PURCHASE_DELAYED": 1,
    "PURCHASE_APPROVED": 2,
    "PURCHASE_CANCELED": 3,
    "PURCHASE_EXPIRED": 3,
    "PURCHASE_PROTEST": 4,
    "PURCHASE_CHARGEBACK": 5,
    "PURCHASE_REFUNDED": 6,
}


def _lock_hotmart_key(db: Session, key: str) -> None:
    # Transaction-scoped locks serialize event and transaction deduplication across API processes.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def lock_hotmart_transaction(db: Session, transaction_id: str) -> None:
    _lock_hotmart_key(db, f"hotmart:transaction:{transaction_id}")


def _valid_hotmart_email(payload: HotmartWebhookPayload) -> str | None:
    email = normalized_buyer_email(payload)
    if email is None:
        return None
    try:
        return validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def _price_cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalized_currency(value: str | None) -> str | None:
    normalized = value.strip().upper() if value else ""
    return normalized or None


def _record_provider_prices(order: Order, payload: HotmartWebhookPayload) -> None:
    purchase = payload.data.purchase
    if purchase.price is not None:
        order.provider_price_cents = _price_cents(purchase.price.value)
        order.provider_price_currency = _normalized_currency(purchase.price.currency_code)
    if purchase.full_price is not None:
        order.provider_full_price_cents = _price_cents(purchase.full_price.value)
        order.provider_full_price_currency = _normalized_currency(purchase.full_price.currency_code)




def apply_hotmart_approval(
    db: Session,
    order: Order,
    product: Product,
    *,
    buyer_email: str | None,
) -> bool:
    """Apply the existing approval transition to a locked pending order."""
    if order.status != "pending":
        return False
    order.status = "paid"
    if buyer_email is not None:
        order.buyer_email_encrypted = encrypt_text(buyer_email, "orders.buyer_email")
        order.buyer_email_hash = email_lookup_hash(buyer_email)
    order.amount_cents = product.price_cents
    order.currency = product.currency
    db.flush()
    license_row = db.scalar(
        select(License).where(License.order_id == order.id).with_for_update()
    )
    if license_row is None:
        if buyer_email is None:
            raise ValueError("buyer_email_required")
        license_row, code = issue_license(db, product, order_id=order.id, buyer_email=buyer_email)
        email_outbox_service.enqueue_email(
            db,
            event_type="license_delivery",
            payload={"to": buyer_email, "code": code, "product_name": product.name},
            idempotency_key=f"license-delivery:{license_row.id}",
            aggregate_id=license_row.id,
        )
    elif license_row.status == "suspended":
        restored_status = "pending" if license_row.tenant_id is None and license_row.activated_at is None else "active"
        license_row.status = restored_status
        license_row.revoked_at = None
    return True


def apply_hotmart_terminal(
    db: Session,
    order: Order,
    *,
    order_status: str,
    license_status: str,
    cancel_reason: str,
) -> bool:
    """Apply an existing terminal commercial transition to a locked non-terminal order."""
    if order.status in _TERMINAL_ORDER_STATUSES:
        return False
    order.status = order_status
    license_row = db.scalar(select(License).where(License.order_id == order.id))
    if license_row is not None:
        if license_row.status not in {"cancelled", "suspended"}:
            license_row.status = license_status
            license_row.revoked_at = datetime.now(timezone.utc)
            if license_row.tenant_id is not None:
                revoke_tenant_sessions(db, license_row.tenant_id)
        email_outbox_service.cancel_license_delivery(db, license_row.id, reason=cancel_reason)
    return True

def process_hotmart_event(db: Session, payload: HotmartWebhookPayload, *, payload_hash: str) -> dict:
    """Apply one authenticated Hotmart event and its outbox effects in one transaction."""
    from app.models.payment_event import PaymentEvent

    provider = "hotmart"
    transaction_id = payload.data.purchase.transaction.strip()
    event_id = payload.id.strip()
    event_type = payload.event
    created_at = event_time(payload)
    priority = _HOTMART_PRIORITY[event_type]
    purchase_status = (payload.data.purchase.status or "").strip().upper()
    if event_type == "PURCHASE_APPROVED" and purchase_status and purchase_status != "APPROVED":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Notificação de compra inválida")
    set_db_context(db, payment_provider=provider)
    try:
        _lock_hotmart_key(db, f"hotmart:event:{event_id}")
        lock_hotmart_transaction(db, transaction_id)

        duplicate = db.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == provider,
                PaymentEvent.external_event_id == event_id,
            )
        )
        if duplicate is not None:
            db.rollback()
            return {"status": "duplicate"}

        product = get_product_by_slug(db, settings.HOTMART_PRODUCT_SLUG)
        if product is None or not product.active:
            raise RuntimeError("hotmart_product_not_configured")

        order = db.scalar(
            select(Order)
            .where(Order.provider == provider, Order.external_order_id == transaction_id)
            .with_for_update()
        )
        if order is None:
            order = Order(
                provider=provider,
                external_order_id=transaction_id,
                product_id=product.id,
                amount_cents=product.price_cents,
                currency=product.currency,
                status="pending",
            )
            db.add(order)
            db.flush()
        elif order.product_id != product.id:
            raise RuntimeError("hotmart_transaction_product_conflict")

        set_db_context(db, payment_provider=provider, payment_order_id=order.id)
        latest = db.scalar(
            select(PaymentEvent)
            .where(PaymentEvent.order_id == order.id, PaymentEvent.provider_event_created_at.is_not(None))
            .order_by(PaymentEvent.provider_event_created_at.desc(), PaymentEvent.state_priority.desc())
            .limit(1)
        )
        newer_than_latest = latest is None or (created_at, priority) > (
            latest.provider_event_created_at,
            latest.state_priority,
        )
        terminal = order.status in _TERMINAL_ORDER_STATUSES
        if newer_than_latest and not terminal:
            if event_type == "PURCHASE_APPROVED":
                if order.status == "pending":
                    buyer_email = _valid_hotmart_email(payload)
                    if buyer_email is None:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Notificação de compra incompleta",
                        )
                    # Product price/currency come only from the internal catalog.
                    _record_provider_prices(order, payload)
                    apply_hotmart_approval(db, order, product, buyer_email=buyer_email)
            elif event_type in {"PURCHASE_REFUNDED", "PURCHASE_CHARGEBACK", "PURCHASE_PROTEST",
                                "PURCHASE_CANCELED", "PURCHASE_EXPIRED"}:
                if event_type == "PURCHASE_REFUNDED":
                    target_status, license_status, cancel_reason = "refunded", "cancelled", "license_revoked"
                elif event_type in {"PURCHASE_CHARGEBACK", "PURCHASE_PROTEST"}:
                    target_status, license_status, cancel_reason = "chargeback", "suspended", "license_suspended"
                else:
                    target_status, license_status, cancel_reason = "cancelled", "cancelled", "license_revoked"
                apply_hotmart_terminal(
                    db,
                    order,
                    order_status=target_status,
                    license_status=license_status,
                    cancel_reason=cancel_reason,
                )
            elif event_type == "PURCHASE_DELAYED":
                order.status = "pending"
                license_row = db.scalar(select(License).where(License.order_id == order.id))
                if license_row is not None and license_row.status not in {"cancelled", "suspended"}:
                    license_row.status = "suspended"
                    license_row.revoked_at = datetime.now(timezone.utc)
                    if license_row.tenant_id is not None:
                        revoke_tenant_sessions(db, license_row.tenant_id)

        db.add(PaymentEvent(
            provider=provider,
            external_event_id=event_id,
            event_type=event_type,
            order_id=order.id,
            payload_hash=payload_hash,
            provider_event_created_at=created_at,
            state_priority=priority,
        ))
        db.commit()
        return {"status": "processed" if newer_than_latest and not terminal else "recorded"}
    except Exception:
        db.rollback()
        raise
