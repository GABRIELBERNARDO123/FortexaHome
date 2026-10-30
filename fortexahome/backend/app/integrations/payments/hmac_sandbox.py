from __future__ import annotations

import hashlib
import hmac
import json

from app.core.config import get_settings
from app.integrations.payments.base import PaymentNotification


class HmacSandboxProvider:
    """Provedor de homologação com assinatura HMAC. Não é uma integração comercial real."""

    name = "hmac_sandbox"

    def verify_and_parse(self, raw_body: bytes, signature: str | None) -> PaymentNotification | None:
        settings = get_settings()
        if not signature or not settings.PAYMENT_WEBHOOK_SECRET:
            return None
        expected = hmac.new(
            settings.PAYMENT_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None

        payload = json.loads(raw_body.decode("utf-8"))
        data = payload.get("data") or {}
        event_id = str(payload.get("id") or "").strip()
        event_type = str(payload.get("type") or "").strip()
        if not event_id or not event_type:
            return None

        if event_type not in {
            "payment.paid",
            "payment.refunded",
            "payment.chargeback",
            "payment.cancelled",
        }:
            return None

        return PaymentNotification(
            event_id=event_id,
            event_type=event_type,
            external_order_id=str(data.get("order_id") or "").strip(),
            product_slug=str(data.get("product_slug") or "").strip(),
            buyer_email=str(data.get("email") or "").strip().lower(),
            amount_cents=int(data.get("amount_cents") or 0),
            currency=str(data.get("currency") or "BRL").upper(),
            customer_id=data.get("customer_id"),
        )
