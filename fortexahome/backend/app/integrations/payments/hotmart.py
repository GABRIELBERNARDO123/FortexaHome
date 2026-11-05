"""Hotmart Webhook 2.0.0 authentication and payload normalization."""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import get_settings


class HotmartProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ucode: str = Field(min_length=1, max_length=120)

    @field_validator("ucode")
    @classmethod
    def _ucode_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ucode must not be blank")
        return value


class HotmartBuyer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: str | None = Field(default=None, max_length=320)
    name: str | None = Field(default=None, max_length=200)


class HotmartPurchasePrice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: Decimal | None = Field(default=None, ge=0)
    currency_code: str | None = Field(default=None, max_length=3)


class HotmartOrderBump(BaseModel):
    model_config = ConfigDict(extra="ignore")
    is_order_bump: bool | None = None
    parent_purchase_transaction: str | None = Field(default=None, max_length=120)

    @field_validator("parent_purchase_transaction")
    @classmethod
    def _blank_parent_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class HotmartPurchase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    transaction: str = Field(min_length=1, max_length=120)
    status: str | None = Field(default=None, max_length=40)
    price: HotmartPurchasePrice | None = None
    full_price: HotmartPurchasePrice | None = None
    order_bump: HotmartOrderBump | None = None

    @field_validator("transaction")
    @classmethod
    def _transaction_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("transaction must not be blank")
        return value


class HotmartData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    product: HotmartProduct
    buyer: HotmartBuyer | None = None
    purchase: HotmartPurchase


class HotmartWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=160)
    creation_date: int = Field(gt=0)
    event: Literal[
        "PURCHASE_APPROVED", "PURCHASE_REFUNDED", "PURCHASE_CHARGEBACK",
        "PURCHASE_PROTEST", "PURCHASE_CANCELED", "PURCHASE_COMPLETE",
        "PURCHASE_DELAYED", "PURCHASE_EXPIRED", "PURCHASE_BILLET_PRINTED",
    ]
    version: Literal["2.0.0"]
    data: HotmartData

    @field_validator("id")
    @classmethod
    def _event_id_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("id must not be blank")
        return value


def authenticate_hottok(received: str | None) -> bool:
    expected = get_settings().HOTMART_WEBHOOK_HOTTOK
    return bool(received and expected and hmac.compare_digest(received, expected))


def parse_payload(raw_body: bytes) -> HotmartWebhookPayload:
    return HotmartWebhookPayload.model_validate_json(raw_body)


def event_time(payload: HotmartWebhookPayload) -> datetime:
    try:
        return datetime.fromtimestamp(payload.creation_date / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("invalid_creation_date") from exc


def normalized_buyer_email(payload: HotmartWebhookPayload) -> str | None:
    value = payload.data.buyer.email if payload.data.buyer else None
    normalized = value.strip().lower() if value else None
    return normalized or None


__all__ = [
    "HotmartWebhookPayload", "ValidationError", "authenticate_hottok", "event_time",
    "normalized_buyer_email", "parse_payload",
]
