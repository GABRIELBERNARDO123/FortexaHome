from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from app.core.config import get_settings
from app.integrations.payments.hotmart_api import HotmartApiClient, HotmartApiConfig
from app.services.hotmart_reconciliation_service import run_reconciliation


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("deve ser um inteiro positivo") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("deve ser um inteiro positivo")
    return parsed


def _print_run(run, *, dry_run: bool, as_json: bool) -> None:
    payload = {
        "run_id": str(run.run_id),
        "dry_run": dry_run,
        "stopped_early": run.stopped_early,
        "transactions": len(run.results),
        "changed": run.changed,
        "manual_review": run.manual,
        "failed": run.failed,
        "results": [asdict(item) | {"order_id": str(item.order_id) if item.order_id else None} for item in run.results],
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    mode = "DRY-RUN" if dry_run else "APLICAÇÃO"
    print(f"Reconciliação Hotmart — {mode} — run_id={run.run_id}")
    for item in run.results:
        print(
            f"[{item.application_result}] tx={item.transaction} "
            f"local={item.local_order_status or '-'} licenca={item.local_license_status or '-'} "
            f"remoto={item.remote_status or '-'} comparacao={item.comparison_result} "
            f"motivo={item.reason or '-'}"
        )
    print(
        f"Resumo: transacoes={len(run.results)} aplicadas={run.changed} "
        f"analise_manual={run.manual} falhas={run.failed} parada_antecipada={run.stopped_early}"
    )
    if dry_run:
        print("Nenhum estado comercial foi alterado. Observações de auditoria foram registradas.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compara pedidos Hotmart locais com a API oficial de vendas"
    )
    parser.add_argument("--transaction", help="consulta uma transação Hotmart específica")
    parser.add_argument("--lookback-hours", type=_positive_int, default=None)
    parser.add_argument("--limit", type=_positive_int, default=None)
    parser.add_argument("--json", action="store_true", help="emite o resumo em JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="aplica transições comerciais permitidas")
    mode.add_argument("--dry-run", action="store_true", help="consulta e compara sem alterar estados (padrão)")
    args = parser.parse_args(argv)

    settings = get_settings()
    dry_run = not args.apply
    if not settings.HOTMART_RECONCILIATION_ENABLED:
        print("[FAIL] reconciliação Hotmart desabilitada; defina HOTMART_RECONCILIATION_ENABLED=true")
        return 2
    missing = [
        name
        for name, value in (
            ("HOTMART_RECONCILIATION_CLIENT_ID", settings.HOTMART_RECONCILIATION_CLIENT_ID),
            ("HOTMART_RECONCILIATION_CLIENT_SECRET", settings.HOTMART_RECONCILIATION_CLIENT_SECRET),
            ("HOTMART_RECONCILIATION_PRODUCT_ID", settings.HOTMART_RECONCILIATION_PRODUCT_ID),
            ("HOTMART_PRODUCT_SLUG", settings.HOTMART_PRODUCT_SLUG),
        )
        if not value.strip()
    ]
    if missing:
        print("[FAIL] configuração da reconciliação incompleta: " + ", ".join(missing))
        return 2

    lookback_hours = args.lookback_hours or settings.HOTMART_RECONCILIATION_LOOKBACK_HOURS
    limit = args.limit or settings.HOTMART_RECONCILIATION_MAX_TRANSACTIONS
    if lookback_hours > 720:
        print("[FAIL] --lookback-hours não pode exceder 720")
        return 2
    if limit > settings.HOTMART_RECONCILIATION_MAX_TRANSACTIONS:
        print(
            "[FAIL] --limit excede HOTMART_RECONCILIATION_MAX_TRANSACTIONS="
            f"{settings.HOTMART_RECONCILIATION_MAX_TRANSACTIONS}"
        )
        return 2

    config = HotmartApiConfig(
        client_id=settings.HOTMART_RECONCILIATION_CLIENT_ID,
        client_secret=settings.HOTMART_RECONCILIATION_CLIENT_SECRET,
        environment=settings.HOTMART_RECONCILIATION_ENVIRONMENT,
        timeout_seconds=settings.HOTMART_RECONCILIATION_TIMEOUT_SECONDS,
        max_attempts=settings.HOTMART_RECONCILIATION_MAX_ATTEMPTS,
        backoff_base_seconds=settings.HOTMART_RECONCILIATION_BACKOFF_BASE_SECONDS,
    )
    try:
        with HotmartApiClient(config) as client:
            run = run_reconciliation(
                transaction=args.transaction,
                lookback_hours=lookback_hours,
                limit=limit,
                dry_run=dry_run,
                client=client,
                request_interval_seconds=settings.HOTMART_RECONCILIATION_REQUEST_INTERVAL_SECONDS,
            )
    except Exception as exc:
        print(f"[FAIL] reconciliação não concluída ({type(exc).__name__})")
        return 1

    _print_run(run, dry_run=dry_run, as_json=args.json)
    if run.stopped_early or run.failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
