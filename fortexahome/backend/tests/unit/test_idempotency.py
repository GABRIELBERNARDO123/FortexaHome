from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.idempotency_service import request_fingerprint, validate_key


def test_idempotency_key_validation_accepts_uuid_and_opaque_tokens():
    key = str(uuid.uuid4())
    assert validate_key(key) == key
    assert validate_key("  pedido-1234.v1:abc  ") == "pedido-1234.v1:abc"
    assert validate_key(None) is None


@pytest.mark.parametrize("value", ["", "   ", "tem espaco", "x" * 129, "chave/errada"])
def test_idempotency_key_rejects_invalid_values(value):
    with pytest.raises(HTTPException) as error:
        validate_key(value)
    assert error.value.status_code == 400


def test_fingerprint_is_canonical_and_changes_with_financial_effect():
    common = {
        "amount": Decimal("100.00"),
        "occurred_on": date(2026, 11, 4),
        "category_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "description": "Mercado",
    }
    reordered = {
        "description": "Mercado",
        "category_id": str(common["category_id"]),
        "occurred_on": "2026-11-04",
        "amount": "100.00",
    }
    assert request_fingerprint(common) == request_fingerprint(reordered)
    assert request_fingerprint(common) != request_fingerprint({**common, "amount": Decimal("100.01")})
