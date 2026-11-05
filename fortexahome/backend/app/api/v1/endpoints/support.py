import uuid
from datetime import date

from fastapi import APIRouter, Query, Request, Response, status

from app.api.v1.cookies import clear_support_session_cookie, set_support_session_cookie
from app.core.rate_limit import limiter
from app.core.support_deps import CurrentSupport, SupportDBSession
from app.core.support_permissions import require_support_permission
from app.schemas.support import (
    SupportAuthResponse,
    SupportLoginRequest,
    SupportPrivacyActionRequest,
    SupportRecoveryActionRequest,
)
from app.services import privacy_service, support_service

router = APIRouter(prefix="/support", tags=["suporte"])


@router.post("/auth/login", response_model=SupportAuthResponse)
@limiter.limit("10/minute", keys=("ip", "email"), scope="support.login")
def support_login(
    request: Request,
    payload: SupportLoginRequest,
    response: Response,
    db: SupportDBSession,
) -> dict:
    token, data = support_service.authenticate_support(
        db, email=payload.email, password=payload.password
    )
    set_support_session_cookie(response, token)
    return data


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def support_logout(ctx: CurrentSupport, response: Response, db: SupportDBSession) -> Response:
    support_service.logout_support(db, ctx.operator, ctx.session.id)
    clear_support_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=SupportAuthResponse)
def support_me(ctx: CurrentSupport) -> dict:
    return support_service.support_me(ctx.operator)


@router.get("/dashboard")
def support_dashboard(ctx: CurrentSupport, db: SupportDBSession) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return support_service.dashboard(db)


@router.get("/orders")
def support_orders(
    ctx: CurrentSupport,
    db: SupportDBSession,
    transaction: str | None = Query(default=None, max_length=120),
    order_status: str | None = Query(default=None, alias="status", max_length=32),
    license_status: str | None = Query(default=None, max_length=32),
    product_slug: str | None = Query(default=None, max_length=80),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return support_service.list_orders(
        db,
        transaction=transaction,
        order_status=order_status,
        license_status=license_status,
        product_slug=product_slug,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )


@router.get("/orders/{order_id}")
def support_order_detail(
    order_id: uuid.UUID,
    ctx: CurrentSupport,
    db: SupportDBSession,
) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return support_service.get_order(db, order_id)


@router.post("/orders/{order_id}/recovery-instructions")
@limiter.limit("30/hour", keys=("support_operator", "ip"), scope="support.recovery_instructions")
def support_recovery_instructions(
    request: Request,
    order_id: uuid.UUID,
    payload: SupportRecoveryActionRequest,
    ctx: CurrentSupport,
    db: SupportDBSession,
) -> dict:
    require_support_permission(ctx.operator, "support:act")
    return support_service.resend_recovery_instructions(
        db,
        ctx.operator,
        order_id=order_id,
        justification=payload.justification,
    )


@router.get("/licenses")
def support_licenses(
    ctx: CurrentSupport,
    db: SupportDBSession,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    product_slug: str | None = Query(default=None, max_length=80),
    transaction: str | None = Query(default=None, max_length=120),
    tenant_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return support_service.list_licenses(
        db,
        status_filter=status_filter,
        product_slug=product_slug,
        transaction=transaction,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
    )


@router.get("/outbox")
def support_outbox(
    ctx: CurrentSupport,
    db: SupportDBSession,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    event_type: str | None = Query(default=None, max_length=64),
    aggregate_id: uuid.UUID | None = Query(default=None),
    transaction: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return support_service.list_outbox(
        db,
        status_filter=status_filter,
        event_type=event_type,
        aggregate_id=aggregate_id,
        transaction=transaction,
        page=page,
        page_size=page_size,
    )


@router.get("/audit")
def support_audit(
    ctx: CurrentSupport,
    db: SupportDBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return support_service.list_audit(db, page=page, page_size=page_size)


@router.get("/privacy/requests")
def support_privacy_requests(
    ctx: CurrentSupport,
    db: SupportDBSession,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    request_type: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return privacy_service.list_support_requests(
        db,
        status_filter=status_filter,
        request_type=request_type,
        page=page,
        page_size=page_size,
    )


@router.get("/privacy/requests/{request_id}")
def support_privacy_request(
    request_id: uuid.UUID,
    ctx: CurrentSupport,
    db: SupportDBSession,
) -> dict:
    require_support_permission(ctx.operator, "support:read")
    return privacy_service.get_support_request(db, request_id)


@router.post("/privacy/requests/{request_id}/approve")
def support_privacy_approve(
    request_id: uuid.UUID,
    payload: SupportPrivacyActionRequest,
    ctx: CurrentSupport,
    db: SupportDBSession,
) -> dict:
    require_support_permission(ctx.operator, "support:act")
    return privacy_service.support_approve(
        db, ctx.operator, request_id=request_id, justification=payload.justification
    )


@router.post("/privacy/requests/{request_id}/reject")
def support_privacy_reject(
    request_id: uuid.UUID,
    payload: SupportPrivacyActionRequest,
    ctx: CurrentSupport,
    db: SupportDBSession,
) -> dict:
    require_support_permission(ctx.operator, "support:act")
    return privacy_service.support_reject(
        db, ctx.operator, request_id=request_id, justification=payload.justification
    )
