from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from app.schemas.product import ProductProvision
from app.services.license_service import (
    CatalogConflictError,
    CatalogPermissionError,
    ProductProvisionResult,
    provision_product,
)


def _print_result(result: ProductProvisionResult, *, apply: bool) -> None:
    labels = {
        "created": "Produto criado",
        "would_create": "DRY-RUN: produto seria criado",
        "updated": "Produto atualizado",
        "would_update": "DRY-RUN: produto seria atualizado",
        "unchanged": "Produto já está no estado desejado",
    }
    product = result.product
    print(
        f"{labels.get(result.action, result.action)}: "
        f"slug={product.slug} name={product.name} price_cents={product.price_cents} "
        f"currency={product.currency} license_kind={product.license_kind} active={product.active}"
    )
    if result.changed_fields:
        print("Campos alterados: " + ", ".join(result.changed_fields))
    if not apply:
        print("Nenhuma alteração foi gravada. Revise e repita com --apply para efetivar.")


def main(argv: list[str] | None = None, *, session_factory=None) -> int:
    parser = argparse.ArgumentParser(
        description="Cria ou atualiza um produto do catálogo interno usando o slug como chave estável"
    )
    parser.add_argument("--slug", required=True, help="slug estável do produto interno")
    parser.add_argument("--name", required=True, help="nome comercial do produto")
    parser.add_argument("--price-cents", required=True, type=int, help="preço interno em centavos")
    parser.add_argument("--currency", required=True, help="moeda ISO de três letras maiúsculas, por exemplo BRL")
    parser.add_argument(
        "--license-kind",
        required=True,
        choices=("lifetime", "subscription"),
        help="tipo de licença definido pelo modelo existente",
    )
    parser.add_argument("--description", default=None, help="descrição opcional do produto")
    parser.add_argument(
        "--state",
        choices=("active", "inactive"),
        default=None,
        help="estado explícito; sem esta opção um produto existente mantém o estado atual",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="efetiva a criação/atualização; sem esta opção o comando apenas simula",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="simula sem gravar (comportamento padrão)",
    )
    args = parser.parse_args(argv)

    try:
        payload = ProductProvision(
            slug=args.slug,
            name=args.name,
            description=args.description,
            price_cents=args.price_cents,
            currency=args.currency,
            license_kind=args.license_kind,
            active=None if args.state is None else args.state == "active",
        )
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            print(f"[FAIL] entrada.{location or 'produto'}: {error.get('msg', 'valor inválido')}")
        return 2

    if session_factory is None:
        from app.core.database import SessionLocal

        session_factory = SessionLocal

    try:
        with session_factory() as db:
            result = provision_product(
                db,
                slug=payload.slug,
                name=payload.name,
                price_cents=payload.price_cents,
                currency=payload.currency,
                license_kind=payload.license_kind,
                description=payload.description,
                description_provided=args.description is not None,
                active=payload.active,
                apply=args.apply,
            )
            if args.apply:
                db.commit()
            _print_result(result, apply=args.apply)
            if not args.apply:
                db.rollback()
    except CatalogConflictError as exc:
        print(f"[FAIL] catálogo: {exc}")
        return 2
    except CatalogPermissionError as exc:
        print(f"[FAIL] catálogo: {exc}")
        return 3
    except Exception:
        print("[FAIL] catálogo: não foi possível provisionar o produto; nenhuma alteração foi confirmada")
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
