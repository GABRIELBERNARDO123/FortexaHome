from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.integrations.payments import hotmart

FIXTURES = Path(__file__).parents[1] / "fixtures" / "hotmart"


@pytest.fixture(params=[
    "PURCHASE_APPROVED", "PURCHASE_REFUNDED", "PURCHASE_CHARGEBACK",
    "PURCHASE_PROTEST", "PURCHASE_CANCELED", "PURCHASE_DELAYED", "PURCHASE_EXPIRED",
    "PURCHASE_COMPLETE", "PURCHASE_BILLET_PRINTED",
])
def official_shaped_event(request):
    event = request.param
    value = {
        "id": f"evt-test-{event.lower()}",
        "creation_date": 1793480400000,
        "event": event,
        "version": "2.0.0",
        "data": {
            "product": {"ucode": "UCODE-FICTICIO-001", "name": "Produto de teste"},
            "buyer": {"email": "comprador-ficticio@example.test", "name": "Pessoa Fictícia"},
            "purchase": {
                "transaction": f"transaction-{event.lower()}",
                "status": event.removeprefix("PURCHASE_"),
                "price": {"value": 999.90, "currency_code": "BRL"},
            },
        },
    }
    if event in {"PURCHASE_BILLET_PRINTED", "PURCHASE_COMPLETE"}:
        value["data"].pop("buyer")
    return value


def test_v2_payloads_parse_and_optional_buyer_is_supported(official_shaped_event):
    parsed = hotmart.parse_payload(json.dumps(official_shaped_event).encode())
    assert parsed.version == "2.0.0"
    assert parsed.event == official_shaped_event["event"]
    assert parsed.data.purchase.transaction


def test_unsupported_version_and_event_are_rejected():
    base = {
        "id": "event", "creation_date": 1793480400000, "event": "PURCHASE_APPROVED",
        "version": "1.0.0", "data": {"product": {"ucode": "X"}, "purchase": {"transaction": "T"}},
    }
    with pytest.raises(hotmart.ValidationError):
        hotmart.parse_payload(json.dumps(base).encode())
    base["version"] = "2.0.0"
    base["event"] = "UNKNOWN"
    with pytest.raises(hotmart.ValidationError):
        hotmart.parse_payload(json.dumps(base).encode())


def test_all_official_event_fixtures_parse():
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) == 9
    events = set()
    for path in files:
        parsed = hotmart.parse_payload(path.read_bytes())
        events.add(parsed.event)
        assert parsed.id.strip()
        assert parsed.data.purchase.transaction.strip()
    assert events == {
        "PURCHASE_APPROVED", "PURCHASE_REFUNDED", "PURCHASE_CHARGEBACK",
        "PURCHASE_PROTEST", "PURCHASE_CANCELED", "PURCHASE_DELAYED",
        "PURCHASE_EXPIRED", "PURCHASE_COMPLETE", "PURCHASE_BILLET_PRINTED",
    }


def test_order_bump_fields_are_parsed_and_empty_parent_is_none():
    base = {
        "id": "evt-bump", "creation_date": 1793480400000, "event": "PURCHASE_APPROVED",
        "version": "2.0.0",
        "data": {
            "product": {"ucode": "UCODE-FICTICIO-001"},
            "buyer": {"email": "comprador-ficticio@example.test"},
            "purchase": {
                "transaction": "tx-bump",
                "status": "APPROVED",
                "price": {"value": 10.0, "currency_code": "BRL"},
                "full_price": {"value": 12.5, "currency_code": "BRL"},
                "order_bump": {"is_order_bump": True, "parent_purchase_transaction": "   "},
            },
        },
    }
    parsed = hotmart.parse_payload(json.dumps(base).encode())
    bump = parsed.data.purchase.order_bump
    assert bump is not None and bump.is_order_bump is True
    assert bump.parent_purchase_transaction is None
    assert parsed.data.purchase.full_price.value == 12.5


@pytest.mark.parametrize("identifier", ["id", "transaction"])
def test_blank_mandatory_identifiers_are_rejected(identifier):
    base = {
        "id": "evt-1", "creation_date": 1793480400000, "event": "PURCHASE_APPROVED",
        "version": "2.0.0",
        "data": {"product": {"ucode": "X"}, "purchase": {"transaction": "tx-1"}},
    }
    if identifier == "id":
        base["id"] = "   "
    else:
        base["data"]["purchase"]["transaction"] = "   "
    with pytest.raises(hotmart.ValidationError):
        hotmart.parse_payload(json.dumps(base).encode())


def test_hottok_comparison_rejects_missing_or_incorrect_value(monkeypatch):
    settings = hotmart.get_settings()
    monkeypatch.setattr(settings, "HOTMART_WEBHOOK_HOTTOK", "fictional-test-hottok-value")
    assert hotmart.authenticate_hottok("fictional-test-hottok-value")
    assert not hotmart.authenticate_hottok(None)
    assert not hotmart.authenticate_hottok("fictional-test-hottok-valuE")


def test_missing_creation_date_is_rejected():
    payload = {
        "id": "evt-no-date",
        "event": "PURCHASE_APPROVED",
        "version": "2.0.0",
        "data": {
            "product": {"ucode": "UCODE-FICTICIO-001"},
            "purchase": {"transaction": "tx-no-date"},
        },
    }
    with pytest.raises(hotmart.ValidationError):
        hotmart.parse_payload(json.dumps(payload).encode())
