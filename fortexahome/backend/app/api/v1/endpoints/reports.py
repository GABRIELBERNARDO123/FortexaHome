from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Response
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DBSession
from app.models.tenant import Tenant
from app.services import report_service
from app.services.periods import parse_month

router = APIRouter(prefix="/reports", tags=["relatórios"])


def _month(db: Session, user, month: str | None):
    tenant = db.get(Tenant, user.tenant_id)
    return parse_month(month, tenant.timezone if tenant else "America/Sao_Paulo")


@router.get("/summary")
def report_summary(
    user: CurrentUser,
    db: DBSession,
    start: date = Query(...),
    end: date = Query(...),
) -> dict:
    return report_service.period_report(db, user.tenant_id, start, end)


@router.get("/monthly")
def monthly_report(
    user: CurrentUser,
    db: DBSession,
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
) -> dict:
    return report_service.monthly_report(db, user.tenant_id, _month(db, user, month))


@router.get("/transactions.csv")
def transactions_csv(
    user: CurrentUser,
    db: DBSession,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
) -> Response:
    content = report_service.transactions_csv(db, user.tenant_id, start=start, end=end)
    filename = f"fortexahome-lancamentos-{date.today().isoformat()}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
