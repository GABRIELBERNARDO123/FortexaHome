from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.product import ProductProvision


def test_product_provision_accepts_existing_catalog_fields():
    product = ProductProvision(
        slug="fortexahome-lifetime",
        name="FortexaHome",
        description="Licença",
        price_cents=19990,
        currency="BRL",
        license_kind="lifetime",
        active=True,
    )
    assert product.slug == "fortexahome-lifetime"
    assert product.price_cents == 19990


@pytest.mark.parametrize(
    "overrides",
    [
        {"slug": "Slug Inválido"},
        {"slug": ""},
        {"name": "   "},
        {"price_cents": -1},
        {"currency": "brl"},
        {"currency": "BR"},
        {"license_kind": "annual"},
        {"description": "x" * 501},
    ],
)
def test_product_provision_rejects_invalid_fields(overrides):
    values = {
        "slug": "valid-slug",
        "name": "Produto",
        "price_cents": 100,
        "currency": "BRL",
        "license_kind": "lifetime",
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        ProductProvision(**values)
