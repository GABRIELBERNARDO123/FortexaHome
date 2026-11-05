from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.preflight import commercial_checks, database_checks, failures
from app.services.license_service import provision_product

pytestmark = pytest.mark.integration


def product_slug() -> str:
    return f"preflight-product-{uuid.uuid4().hex[:16]}"


def create_product(*, active: bool = True) -> str:
    slug = product_slug()
    with SessionLocal() as db:
        provision_product(
            db,
            slug=slug,
            name="Produto de preflight",
            price_cents=19990,
            currency="BRL",
            license_kind="lifetime",
            active=active,
            apply=True,
        )
        db.commit()
    return slug


def test_database_preflight_reports_head_role_permissions_and_catalog_rls():
    settings = get_settings()
    results = database_checks(settings, engine=engine)
    assert not failures(results), [item.message for item in failures(results)]
    assert any(item.code == "database.alembic" and item.level == "OK" for item in results)
    assert any(item.code == "database.privileges" and item.level == "OK" for item in results)
    assert any(item.code == "database.rls" and item.level == "OK" for item in results)


def test_commercial_preflight_skips_when_hotmart_is_disabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "HOTMART_ENABLED", False)
    with SessionLocal() as db:
        results = commercial_checks(settings, db)
    assert results[0].level == "SKIP"
    assert not failures(results)


def test_commercial_preflight_fails_without_product(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "HOTMART_ENABLED", True)
    monkeypatch.setattr(settings, "HOTMART_PRODUCT_SLUG", product_slug())
    with SessionLocal() as db:
        results = commercial_checks(settings, db)
    assert {item.code for item in failures(results)} == {"commercial.product"}


def test_commercial_preflight_fails_for_inactive_product(monkeypatch):
    settings = get_settings()
    slug = create_product(active=False)
    monkeypatch.setattr(settings, "HOTMART_ENABLED", True)
    monkeypatch.setattr(settings, "HOTMART_PRODUCT_SLUG", slug)
    with SessionLocal() as db:
        results = commercial_checks(settings, db)
    assert {item.code for item in failures(results)} == {"commercial.product"}
    assert "inativo" in results[0].message


def test_commercial_preflight_passes_for_active_product(monkeypatch):
    settings = get_settings()
    slug = create_product(active=True)
    monkeypatch.setattr(settings, "HOTMART_ENABLED", True)
    monkeypatch.setattr(settings, "HOTMART_PRODUCT_SLUG", slug)
    with SessionLocal() as db:
        results = commercial_checks(settings, db)
    assert not failures(results)
    assert results[0].level == "OK"
