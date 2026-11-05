from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.cli import provision_product as catalog_cli
from app.core.config import get_settings
from app.core.database import SessionLocal, set_db_context
from app.models.product import Product
from app.services.license_service import (
    CatalogPermissionError,
    provision_product,
)

pytestmark = pytest.mark.integration


def slug() -> str:
    return f"catalog-test-{uuid.uuid4().hex[:16]}"


def provision(db: Session, product_slug: str, **overrides):
    values = {
        "slug": product_slug,
        "name": "Produto de catálogo",
        "price_cents": 19990,
        "currency": "BRL",
        "license_kind": "lifetime",
        "description": "Produto fictício de teste",
        "description_provided": True,
        "apply": True,
    }
    values.update(overrides)
    return provision_product(db, **values)


def count_slug(product_slug: str) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(Product).where(Product.slug == product_slug)) or 0)


def test_provision_creates_and_is_idempotent():
    product_slug = slug()
    with SessionLocal() as db:
        created = provision(db, product_slug)
        db.commit()
    assert created.action == "created"
    assert created.product.slug == product_slug
    assert count_slug(product_slug) == 1

    with SessionLocal() as db:
        repeated = provision(db, product_slug)
        db.commit()
    assert repeated.action == "unchanged"
    assert repeated.changed_fields == ()
    assert count_slug(product_slug) == 1


def test_provision_dry_run_does_not_create_or_update():
    product_slug = slug()
    with SessionLocal() as db:
        result = provision(db, product_slug, apply=False)
        db.rollback()
    assert result.action == "would_create"
    assert count_slug(product_slug) == 0

    with SessionLocal() as db:
        provision(db, product_slug)
        db.commit()
    with SessionLocal() as db:
        result = provision(db, product_slug, name="Nome novo", apply=False)
        db.rollback()
    assert result.action == "would_update"
    assert "name" in result.changed_fields
    with SessionLocal() as db:
        assert db.scalar(select(Product.name).where(Product.slug == product_slug)) == "Produto de catálogo"


def test_provision_updates_controlled_fields_without_duplicate():
    product_slug = slug()
    with SessionLocal() as db:
        provision(db, product_slug)
        db.commit()
    with SessionLocal() as db:
        result = provision(
            db,
            product_slug,
            name="Nome atualizado",
            price_cents=24990,
            description="Descrição atualizada",
        )
        db.commit()
    assert result.action == "updated"
    assert set(result.changed_fields) == {"name", "price_cents", "description"}
    assert count_slug(product_slug) == 1
    with SessionLocal() as db:
        product = db.scalar(select(Product).where(Product.slug == product_slug))
        assert product.name == "Nome atualizado"
        assert product.price_cents == 24990
        assert product.description == "Descrição atualizada"


def test_provision_does_not_reactivate_inactive_without_explicit_state():
    product_slug = slug()
    with SessionLocal() as db:
        provision(db, product_slug, active=False)
        db.commit()
    with SessionLocal() as db:
        provision(db, product_slug, name="Nome novo")
        db.commit()
    with SessionLocal() as db:
        assert db.scalar(select(Product.active).where(Product.slug == product_slug)) is False
    with SessionLocal() as db:
        result = provision(db, product_slug, active=True)
        db.commit()
    assert "active" in result.changed_fields
    with SessionLocal() as db:
        assert db.scalar(select(Product.active).where(Product.slug == product_slug)) is True


def test_duplicate_slug_is_rejected_by_database_constraint():
    product_slug = slug()
    with SessionLocal() as db:
        provision(db, product_slug)
        db.commit()
    with SessionLocal() as db:
        set_db_context(db, catalog_write="true")
        db.add(
            Product(
                slug=product_slug,
                name="Duplicado",
                price_cents=1,
                currency="BRL",
                license_kind="lifetime",
                active=True,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    assert count_slug(product_slug) == 1


def test_rls_blocks_catalog_write_without_catalog_context():
    product_slug = slug()
    with SessionLocal() as db:
        db.add(
            Product(
                slug=product_slug,
                name="Sem contexto",
                price_cents=1,
                currency="BRL",
                license_kind="lifetime",
                active=True,
            )
        )
        with pytest.raises(DBAPIError):
            db.flush()
        db.rollback()
    assert count_slug(product_slug) == 0


def test_provisioning_role_without_catalog_permissions_fails():
    settings = get_settings()
    worker_url = make_url(settings.DATABASE_URL).set(
        username=settings.OUTBOX_DB_USER,
        password=settings.OUTBOX_DB_PASSWORD,
    )
    worker_engine = create_engine(worker_url)
    worker_session = sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False)
    try:
        with worker_session() as db:
            with pytest.raises(CatalogPermissionError):
                provision(db, slug())
    finally:
        worker_engine.dispose()


def test_cli_rolls_back_when_commit_fails():
    product_slug = slug()

    def failing_factory():
        db = SessionLocal()
        db.commit = lambda: (_ for _ in ()).throw(RuntimeError("commit failed"))
        return db

    code = catalog_cli.main(
        [
            "--slug",
            product_slug,
            "--name",
            "Produto com rollback",
            "--price-cents",
            "100",
            "--currency",
            "BRL",
            "--license-kind",
            "lifetime",
            "--apply",
        ],
        session_factory=failing_factory,
    )
    assert code == 3
    assert count_slug(product_slug) == 0


def test_cli_dry_run_then_apply():
    product_slug = slug()
    args = [
        "--slug",
        product_slug,
        "--name",
        "Produto via CLI",
        "--price-cents",
        "100",
        "--currency",
        "BRL",
        "--license-kind",
        "lifetime",
        "--description",
        "Descrição via CLI",
    ]
    assert catalog_cli.main([*args, "--dry-run"]) == 0
    assert count_slug(product_slug) == 0
    assert catalog_cli.main([*args, "--apply"]) == 0
    assert count_slug(product_slug) == 1
    assert catalog_cli.main([*args, "--apply"]) == 0
    assert count_slug(product_slug) == 1
    assert catalog_cli.main([*args, "--name", "Nome apenas simulado", "--dry-run"]) == 0
    with SessionLocal() as db:
        assert db.scalar(select(Product.name).where(Product.slug == product_slug)) == "Produto via CLI"
