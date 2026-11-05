from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from app.services.support_service import provision_support_operator


def main(argv: list[str] | None = None, *, session_factory=None) -> int:
    parser = argparse.ArgumentParser(
        description="Cria ou atualiza um operador de suporte do FortexaHome"
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=("support_read", "support_operator"))
    parser.add_argument("--password-stdin", action="store_true", help="lê a senha da entrada padrão")
    parser.add_argument("--state", choices=("active", "disabled"), default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    password = None
    if args.password_stdin:
        password = sys.stdin.readline().strip()
        if len(password) < 12:
            print("[FAIL] senha deve ter pelo menos 12 caracteres")
            return 2

    if session_factory is None:
        from app.core.database import SessionLocal

        session_factory = SessionLocal

    try:
        with session_factory() as db:
            result = provision_support_operator(
                db,
                email=args.email,
                name=args.name,
                role=args.role,
                password=password,
                active=None if args.state is None else args.state == "active",
                apply=args.apply,
            )
            if args.apply:
                db.commit()
            else:
                db.rollback()
            operator = result["operator"]
            print(
                f"{result['action']}: id={operator['id']} email={operator['email']} "
                f"role={operator['role']} status={operator['status']}"
            )
            if result.get("changed_fields"):
                print("Campos alterados: " + ", ".join(result["changed_fields"]))
            if not args.apply:
                print("Nenhuma alteração foi gravada. Repita com --apply para efetivar.")
            return 0
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            print(f"[FAIL] entrada.{location or 'operador'}: {error.get('msg', 'valor inválido')}")
        return 2
    except ValueError as exc:
        print(f"[FAIL] operador: {exc}")
        return 2
    except Exception:
        print("[FAIL] operador: não foi possível provisionar o operador")
        return 3


if __name__ == "__main__":
    sys.exit(main())
