from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, set_db_context
from app.core.field_encryption import decrypt_text
from app.integrations.payments.hotmart_api import (
    HotmartApiClient,
    HotmartApiError,
    HotmartTransactionObservation,
)
from app.models.hotmart_reconciliation import HotmartReconciliationObservation
from app.models.license import License
from app.models.order import Order
from app.models.payment_event import PaymentEvent
from app.services import license_service

settings = get_settings()
logger = logging.getLogger("fortexahome.hotmart.reconciliation")

_TERMINAL_ORDER_STATUSES = frozenset({"refunded", "chargeback", "cancelled"})
_TERMINAL_REMOTE = {
    "REFUNDED": ("refunded", "cancelled", "license_revoked"),
    "CHARGEBACK": ("chargeback", "suspended", "license_suspended"),
    "PROTESTED": ("chargeback", "suspended", "license_suspended"),
    "CANCELLED": ("cancelled", "cancelled", "license_revoked"),
    "EXPIRED": ("cancelled", "cancelled", "license_revoked"),
}
_INFORMATIONAL_REMOTE = frozenset(
    {
        "COMPLETE",
        "PRINTED_BILLET",
        "PROCESSING_TRANSACTION",
        "STARTED",
        "UNDER_ANALISYS",
        "WAITING_PAYMENT",
        "PRE_ORDER",
        "OVERDUE",
    }
)
_MANUAL_REMOTE = frozenset({"BLOCKED", "PARTIALLY_REFUNDED", "NO_FUNDS"})
_MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True)
class ReconciliationSnapshot:
    order_id: uuid.UUID
    order_updated_at: datetime
    order_status: str
    license_status: str | None
    has_buyer_email: bool
    latest_event_id: str | None
    latest_event_created_at: datetime | None
    latest_event_priority: int | None


@dataclass(frozen=True)
class ReconciliationResult:
    transaction: str
    order_id: uuid.UUID | None
    remote_status: str | None
    local_order_status: str | None
    local_license_status: str | None
    comparison_result: str
    application_result: str
    reason: str | None
    dry_run: bool
    error_code: str | None = None


@dataclass(frozen=True)
class ReconciliationRun:
    run_id: uuid.UUID
    results: list[ReconciliationResult]
    stopped_early: bool

    @property
    def changed(self) -> int:
        return sum(1 for item in self.results if item.application_result == "applied")

    @property
    def manual(self) -> int:
        return sum(1 for item in self.results if item.comparison_result == "manual_review")

    @property
    def failed(self) -> int:
        return sum(1 for item in self.results if item.comparison_result == "error")


def _event_fingerprint(db: Session, order_id: uuid.UUID) -> tuple[str | None, datetime | None, int | None]:
    event = db.scalar(
        select(PaymentEvent)
        .where(PaymentEvent.order_id == order_id, PaymentEvent.provider_event_created_at.is_not(None))
        .order_by(PaymentEvent.provider_event_created_at.desc(), PaymentEvent.state_priority.desc())
        .limit(1)
    )
    if event is None:
        return None, None, None
    return event.external_event_id, event.provider_event_created_at, event.state_priority


def _snapshot(db: Session, order: Order, license_row: License | None) -> ReconciliationSnapshot:
    event_id, event_created, event_priority = _event_fingerprint(db, order.id)
    return ReconciliationSnapshot(
        order_id=order.id,
        order_updated_at=order.updated_at,
        order_status=order.status,
        license_status=license_row.status if license_row else None,
        has_buyer_email=bool(order.buyer_email_encrypted),
        latest_event_id=event_id,
        latest_event_created_at=event_created,
        latest_event_priority=event_priority,
    )


def _load_local(db: Session, transaction: str) -> tuple[Order | None, License | None, ReconciliationSnapshot | None]:
    set_db_context(db, payment_provider="hotmart")
    order = db.scalar(
        select(Order).where(Order.provider == "hotmart", Order.external_order_id == transaction)
    )
    if order is None:
        return None, None, None
    set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
    license_row = db.scalar(select(License).where(License.order_id == order.id))
    return order, license_row, _snapshot(db, order, license_row)


def _load_local_for_update(
    db: Session, transaction: str
) -> tuple[Order | None, License | None, ReconciliationSnapshot | None]:
    set_db_context(db, payment_provider="hotmart")
    license_service.lock_hotmart_transaction(db, transaction)
    order = db.scalar(
        select(Order)
        .where(Order.provider == "hotmart", Order.external_order_id == transaction)
        .with_for_update()
    )
    if order is None:
        return None, None, None
    set_db_context(db, payment_provider="hotmart", payment_order_id=order.id)
    license_row = db.scalar(select(License).where(License.order_id == order.id))
    return order, license_row, _snapshot(db, order, license_row)


def _same_snapshot(left: ReconciliationSnapshot, right: ReconciliationSnapshot) -> bool:
    return left == right


def _product_reason(
    order: Order,
    product,
    observation: HotmartTransactionObservation,
) -> str | None:
    if product is None or not product.active:
        return "configured_product_unavailable"
    if order.product_id != product.id:
        return "local_product_conflict"
    expected_id = settings.HOTMART_RECONCILIATION_PRODUCT_ID.strip()
    if not expected_id:
        return "reconciliation_product_id_missing"
    if observation.product_id is None:
        return "remote_product_missing"
    if str(observation.product_id) != expected_id:
        return "remote_product_mismatch"
    expected_ucode = settings.HOTMART_PRODUCT_UCODE.strip()
    if observation.product_ucode and expected_ucode and observation.product_ucode != expected_ucode:
        return "remote_product_ucode_mismatch"
    if (
        observation.price_currency
        and order.provider_price_currency
        and observation.price_currency != order.provider_price_currency
    ):
        return "provider_currency_mismatch"
    if (
        observation.price_cents is not None
        and order.provider_price_cents is not None
        and observation.price_cents != order.provider_price_cents
    ):
        return "provider_price_mismatch"
    return None


def decide_reconciliation(
    local_order_status: str,
    local_license_status: str | None,
    has_buyer_email: bool,
    remote_status: str,
) -> tuple[str, str, str | None]:
    """Return (comparison_result, action, reason)."""
    if remote_status == "APPROVED":
        if local_order_status == "paid":
            if local_license_status in {"active", "pending"}:
                return "consistent", "no_change", "remote_approved_local_paid"
            return "manual_review", "manual", "paid_with_unexpected_license_state"
        if local_order_status == "pending":
            if local_license_status in {None, "suspended"}:
                if local_license_status is None and not has_buyer_email:
                    return "manual_review", "manual", "buyer_email_missing"
                return "correctable", "approval", "remote_approved_local_pending"
            if local_license_status == "pending":
                return "correctable", "approval", "remote_approved_local_pending"
            return "manual_review", "manual", "pending_with_unexpected_license_state"
        return "manual_review", "manual", "remote_approved_local_terminal"

    if remote_status in _TERMINAL_REMOTE:
        target_order, _, _ = _TERMINAL_REMOTE[remote_status]
        if local_order_status in _TERMINAL_ORDER_STATUSES:
            if local_order_status == target_order:
                return "consistent", "no_change", f"remote_{remote_status.lower()}_local_terminal"
            return "manual_review", "manual", "terminal_state_conflict"
        if local_order_status in {"pending", "paid"}:
            return "correctable", f"terminal:{remote_status}", f"remote_{remote_status.lower()}_local_{local_order_status}"
        return "manual_review", "manual", "unsupported_local_state"

    if remote_status in _INFORMATIONAL_REMOTE:
        if local_order_status in _TERMINAL_ORDER_STATUSES:
            return "manual_review", "manual", "remote_nonterminal_local_terminal"
        if local_order_status == "pending":
            return "consistent", "no_change", f"remote_{remote_status.lower()}_local_pending"
        if remote_status == "COMPLETE" and local_order_status == "paid":
            return "consistent", "no_change", "remote_complete_local_paid"
        return "manual_review", "manual", "remote_status_behind_local"

    if remote_status in _MANUAL_REMOTE:
        return "manual_review", "manual", f"remote_{remote_status.lower()}_requires_review"
    return "manual_review", "manual", "unknown_remote_status"


def _record(
    db: Session,
    *,
    run_id: uuid.UUID,
    transaction: str,
    order_id: uuid.UUID | None,
    observation: HotmartTransactionObservation | None,
    snapshot: ReconciliationSnapshot | None,
    comparison_result: str,
    application_result: str,
    reason: str | None,
    error_code: str | None,
    observed_at: datetime,
    dry_run: bool,
) -> HotmartReconciliationObservation:
    row = HotmartReconciliationObservation(
        run_id=run_id,
        provider="hotmart",
        source="hotmart_sales_api",
        external_order_id=transaction,
        order_id=order_id,
        remote_status=observation.status if observation else None,
        remote_product_id=observation.product_id if observation else None,
        local_order_status=snapshot.order_status if snapshot else None,
        local_license_status=snapshot.license_status if snapshot else None,
        local_updated_at=snapshot.order_updated_at if snapshot else None,
        comparison_result=comparison_result,
        application_result=application_result,
        reason=reason,
        error_code=error_code,
        remote_order_date=observation.order_date if observation else None,
        remote_approved_date=observation.approved_date if observation else None,
        observed_at=observed_at,
        dry_run=dry_run,
    )
    db.add(row)
    db.flush()
    return row


def _result(
    *,
    transaction: str,
    order_id: uuid.UUID | None,
    observation: HotmartTransactionObservation | None,
    snapshot: ReconciliationSnapshot | None,
    comparison_result: str,
    application_result: str,
    reason: str | None,
    dry_run: bool,
    error_code: str | None = None,
) -> ReconciliationResult:
    return ReconciliationResult(
        transaction=transaction,
        order_id=order_id,
        remote_status=observation.status if observation else None,
        local_order_status=snapshot.order_status if snapshot else None,
        local_license_status=snapshot.license_status if snapshot else None,
        comparison_result=comparison_result,
        application_result=application_result,
        reason=reason,
        dry_run=dry_run,
        error_code=error_code,
    )


def _store_result(
    *,
    run_id: uuid.UUID,
    transaction: str,
    observation: HotmartTransactionObservation | None,
    snapshot: ReconciliationSnapshot | None,
    comparison_result: str,
    application_result: str,
    reason: str | None,
    observed_at: datetime,
    dry_run: bool,
    error_code: str | None = None,
) -> ReconciliationResult:
    with SessionLocal() as db:
        _record(
            db,
            run_id=run_id,
            transaction=transaction,
            order_id=snapshot.order_id if snapshot else None,
            observation=observation,
            snapshot=snapshot,
            comparison_result=comparison_result,
            application_result=application_result,
            reason=reason,
            error_code=error_code,
            observed_at=observed_at,
            dry_run=dry_run,
        )
        db.commit()
    return _result(
        transaction=transaction,
        order_id=snapshot.order_id if snapshot else None,
        observation=observation,
        snapshot=snapshot,
        comparison_result=comparison_result,
        application_result=application_result,
        reason=reason,
        dry_run=dry_run,
        error_code=error_code,
    )


def reconcile_transaction(
    transaction: str,
    *,
    run_id: uuid.UUID,
    client: HotmartApiClient,
    dry_run: bool,
) -> ReconciliationResult:
    transaction = transaction.strip()
    with SessionLocal() as db:
        _, _, snapshot = _load_local(db, transaction)

    try:
        observation = client.fetch_transaction(transaction)
    except HotmartApiError as exc:
        observed_at = datetime.now(timezone.utc)
        return _store_result(
            run_id=run_id,
            transaction=transaction,
            observation=None,
            snapshot=snapshot,
            comparison_result="error",
            application_result="failed",
            reason=exc.code,
            error_code=exc.code,
            observed_at=observed_at,
            dry_run=dry_run,
        )
    except Exception as exc:  # Defensive: never persist raw exception text.
        observed_at = datetime.now(timezone.utc)
        return _store_result(
            run_id=run_id,
            transaction=transaction,
            observation=None,
            snapshot=snapshot,
            comparison_result="error",
            application_result="failed",
            reason="unexpected_api_error",
            error_code=type(exc).__name__,
            observed_at=observed_at,
            dry_run=dry_run,
        )

    observed_at = datetime.now(timezone.utc)
    if observation is None:
        return _store_result(
            run_id=run_id,
            transaction=transaction,
            observation=None,
            snapshot=snapshot,
            comparison_result="remote_not_found",
            application_result="dry_run" if dry_run else "no_change",
            reason="transaction_not_returned_by_hotmart",
            observed_at=observed_at,
            dry_run=dry_run,
        )
    if snapshot is None:
        return _store_result(
            run_id=run_id,
            transaction=transaction,
            observation=observation,
            snapshot=None,
            comparison_result="local_order_missing",
            application_result="dry_run" if dry_run else "rejected",
            reason="local_order_not_created_by_reconciliation",
            observed_at=observed_at,
            dry_run=dry_run,
        )

    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        current_order = db.scalar(
            select(Order).where(Order.provider == "hotmart", Order.external_order_id == transaction)
        )
        product = license_service.get_product_by_slug(db, settings.HOTMART_PRODUCT_SLUG)
        product_reason = (
            _product_reason(current_order, product, observation) if current_order is not None else "local_order_missing"
        )
    if product_reason is not None:
        return _store_result(
            run_id=run_id,
            transaction=transaction,
            observation=observation,
            snapshot=snapshot,
            comparison_result="manual_review",
            application_result="dry_run" if dry_run else "rejected",
            reason=product_reason,
            observed_at=observed_at,
            dry_run=dry_run,
        )

    comparison, action, reason = decide_reconciliation(
        snapshot.order_status,
        snapshot.license_status,
        snapshot.has_buyer_email,
        observation.status,
    )
    if dry_run:
        return _store_result(
            run_id=run_id,
            transaction=transaction,
            observation=observation,
            snapshot=snapshot,
            comparison_result=comparison,
            application_result="dry_run",
            reason=reason,
            observed_at=observed_at,
            dry_run=True,
        )
    if action == "manual" or comparison == "correctable":
        # correctable still needs the apply path below; manual never mutates.
        if action == "manual":
            return _store_result(
                run_id=run_id,
                transaction=transaction,
                observation=observation,
                snapshot=snapshot,
                comparison_result=comparison,
                application_result="rejected",
                reason=reason,
                observed_at=observed_at,
                dry_run=False,
            )

    if action == "no_change":
        return _store_result(
            run_id=run_id,
            transaction=transaction,
            observation=observation,
            snapshot=snapshot,
            comparison_result=comparison,
            application_result="no_change",
            reason=reason,
            observed_at=observed_at,
            dry_run=False,
        )

    try:
        with SessionLocal() as db:
            current_order, current_license, current_snapshot = _load_local_for_update(db, transaction)
            if current_order is None or current_snapshot is None:
                return _store_result(
                    run_id=run_id,
                    transaction=transaction,
                    observation=observation,
                    snapshot=snapshot,
                    comparison_result="stale",
                    application_result="rejected",
                    reason="local_order_disappeared",
                    observed_at=observed_at,
                    dry_run=False,
                )
            if not _same_snapshot(snapshot, current_snapshot):
                db.rollback()
                return _store_result(
                    run_id=run_id,
                    transaction=transaction,
                    observation=observation,
                    snapshot=snapshot,
                    comparison_result="stale",
                    application_result="rejected",
                    reason="local_state_changed_during_remote_call",
                    observed_at=observed_at,
                    dry_run=False,
                )

            product = license_service.get_product_by_slug(db, settings.HOTMART_PRODUCT_SLUG)
            product_reason = _product_reason(current_order, product, observation)
            if product_reason is not None:
                db.rollback()
                return _store_result(
                    run_id=run_id,
                    transaction=transaction,
                    observation=observation,
                    snapshot=snapshot,
                    comparison_result="manual_review",
                    application_result="rejected",
                    reason=product_reason,
                    observed_at=observed_at,
                    dry_run=False,
                )

            current_comparison, current_action, current_reason = decide_reconciliation(
                current_order.status,
                current_license.status if current_license else None,
                bool(current_order.buyer_email_encrypted),
                observation.status,
            )
            if current_comparison != comparison or current_action != action:
                db.rollback()
                return _store_result(
                    run_id=run_id,
                    transaction=transaction,
                    observation=observation,
                    snapshot=snapshot,
                    comparison_result="stale",
                    application_result="rejected",
                    reason="decision_changed_after_revalidation",
                    observed_at=observed_at,
                    dry_run=False,
                )

            applied = False
            if action == "approval":
                email = decrypt_text(current_order.buyer_email_encrypted, "orders.buyer_email")
                if email is None and current_license is None:
                    db.rollback()
                    return _store_result(
                        run_id=run_id,
                        transaction=transaction,
                        observation=observation,
                        snapshot=snapshot,
                        comparison_result="manual_review",
                        application_result="rejected",
                        reason="buyer_email_missing",
                        observed_at=observed_at,
                        dry_run=False,
                    )
                if product is None:
                    raise RuntimeError("configured_product_unavailable")
                applied = license_service.apply_hotmart_approval(
                    db,
                    current_order,
                    product,
                    buyer_email=email,
                )
            elif action.startswith("terminal:"):
                remote_name = action.split(":", 1)[1]
                target_order, target_license, cancel_reason = _TERMINAL_REMOTE[remote_name]
                applied = license_service.apply_hotmart_terminal(
                    db,
                    current_order,
                    order_status=target_order,
                    license_status=target_license,
                    cancel_reason=cancel_reason,
                )
            else:
                raise RuntimeError("reconciliation_action_unknown")

            application = "applied" if applied else "no_change"
            _record(
                db,
                run_id=run_id,
                transaction=transaction,
                order_id=current_order.id,
                observation=observation,
                snapshot=snapshot,
                comparison_result=comparison,
                application_result=application,
                reason=current_reason,
                error_code=None,
                observed_at=observed_at,
                dry_run=False,
            )
            db.commit()
            return _result(
                transaction=transaction,
                order_id=current_order.id,
                observation=observation,
                snapshot=snapshot,
                comparison_result=comparison,
                application_result=application,
                reason=current_reason,
                dry_run=False,
            )
    except Exception as exc:
        logger.error("Falha ao aplicar reconciliação Hotmart (%s)", type(exc).__name__)
        try:
            return _store_result(
                run_id=run_id,
                transaction=transaction,
                observation=observation,
                snapshot=snapshot,
                comparison_result="error",
                application_result="failed",
                reason="apply_failed",
                error_code=type(exc).__name__,
                observed_at=observed_at,
                dry_run=False,
            )
        except Exception:
            raise


def select_transactions(
    *,
    transaction: str | None,
    lookback_hours: int,
    limit: int,
) -> list[str]:
    if transaction:
        return [transaction.strip()]
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    with SessionLocal() as db:
        set_db_context(db, payment_provider="hotmart")
        rows = db.scalars(
            select(Order.external_order_id)
            .where(Order.provider == "hotmart", Order.updated_at >= since)
            .order_by(Order.updated_at.desc())
            .limit(limit)
        ).all()
    return list(rows)


def run_reconciliation(
    *,
    transaction: str | None,
    lookback_hours: int,
    limit: int,
    dry_run: bool,
    client: HotmartApiClient,
    request_interval_seconds: float = 0.0,
    run_id: uuid.UUID | None = None,
) -> ReconciliationRun:
    run_id = run_id or uuid.uuid4()
    transactions = select_transactions(
        transaction=transaction,
        lookback_hours=lookback_hours,
        limit=limit,
    )
    results: list[ReconciliationResult] = []
    consecutive_failures = 0
    stopped_early = False
    for index, transaction_id in enumerate(transactions):
        if index > 0 and request_interval_seconds > 0:
            time.sleep(request_interval_seconds)
        result = reconcile_transaction(
            transaction_id,
            run_id=run_id,
            client=client,
            dry_run=dry_run,
        )
        results.append(result)
        if result.comparison_result == "error":
            consecutive_failures += 1
        else:
            consecutive_failures = 0
        if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            stopped_early = True
            logger.error("Reconciliação Hotmart interrompida após falhas consecutivas")
            break
    return ReconciliationRun(run_id=run_id, results=results, stopped_early=stopped_early)


__all__ = [
    "ReconciliationResult",
    "ReconciliationRun",
    "ReconciliationSnapshot",
    "decide_reconciliation",
    "reconcile_transaction",
    "run_reconciliation",
    "select_transactions",
]
