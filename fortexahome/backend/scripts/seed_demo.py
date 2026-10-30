"""Cria o produto e a licença de demonstração local. Nunca use em produção."""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services import license_service


def main() -> int:
    settings = get_settings()
    if settings.is_production or not settings.DEMO_MODE:
        print("Seed de demonstração bloqueado: requer ENV=development e DEMO_MODE=true.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        result = license_service.seed_demo(db)
    print(f"Produto: {result['product']}")
    print(f"Licença demo: {result['code']} ({'criada' if result['created'] else 'já existia'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
