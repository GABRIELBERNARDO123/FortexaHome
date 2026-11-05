from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from app.core.config import Settings
from app.core.preflight import (
    CheckResult,
    commercial_checks,
    database_checks,
    environment_checks,
    failures,
    validation_error_results,
)

_STAGES = ("environment", "database", "commercial", "all")


def _print(results: list[CheckResult]) -> None:
    for item in results:
        print(f"[{item.level}] {item.code}: {item.message}")


def _summary(results: list[CheckResult]) -> str:
    counts = {level: 0 for level in ("OK", "WARN", "FAIL", "SKIP")}
    for item in results:
        counts[item.level] = counts.get(item.level, 0) + 1
    return " ".join(f"{level}={counts[level]}" for level in ("OK", "WARN", "FAIL", "SKIP"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifica o ambiente, o banco e a prontidão comercial do FortexaHome"
    )
    parser.add_argument(
        "--stage",
        choices=_STAGES,
        default="all",
        help="environment antes das migrations; database após migrations; commercial antes de habilitar a Hotmart",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="trata avisos como falha de preflight",
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except ValidationError as exc:
        results = validation_error_results(exc)
        _print(results)
        print(f"Resumo: {_summary(results)}")
        return 1
    except Exception:
        print("[FAIL] config.settings: não foi possível carregar a configuração")
        return 1

    results: list[CheckResult] = []
    if args.stage in {"environment", "all"}:
        results.extend(environment_checks(settings))

    if args.stage in {"database", "all"}:
        results.extend(database_checks(settings))

    if args.stage in {"commercial", "all"}:
        if not settings.HOTMART_ENABLED:
            results.append(
                CheckResult(
                    "SKIP",
                    "commercial.hotmart",
                    "Hotmart desabilitada: credenciais e catálogo comercial não exigidos",
                )
            )
        else:
            from app.core.database import SessionLocal

            try:
                with SessionLocal() as db:
                    results.extend(commercial_checks(settings, db))
            except Exception:
                results.append(
                    CheckResult(
                        "FAIL",
                        "commercial.database",
                        "não foi possível abrir sessão para verificar o catálogo comercial",
                    )
                )

    _print(results)
    print(f"Resumo: {_summary(results)}")
    has_failures = bool(failures(results))
    has_warnings = any(item.level == "WARN" for item in results)
    return 1 if has_failures or (args.strict and has_warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
