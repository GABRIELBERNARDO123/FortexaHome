import uuid

from fastapi import APIRouter, Request, Response, status

from app.api.v1.cookies import clear_session_cookie
from app.core.deps import CurrentAuth, CurrentUser, DBSession
from app.core.rate_limit import limiter
from app.schemas.privacy import PrivacyRequestCreate, PrivacyRequestDetail, PrivacyRequestPublic
from app.services import privacy_service

router = APIRouter(prefix="/privacy", tags=["privacidade"])


@router.post("/requests", response_model=PrivacyRequestPublic, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour", keys=("user", "ip"), scope="privacy.request")
def create_privacy_request(
    request: Request,
    payload: PrivacyRequestCreate,
    response: Response,
    ctx: CurrentAuth,
    db: DBSession,
) -> dict:
    result = privacy_service.create_erasure_request(
        db, user=ctx.user, password=payload.password, reason=payload.reason
    )
    if result["status"] in {"completed", "partially_completed", "cancelled"}:
        clear_session_cookie(response)
    return result


@router.get("/requests", response_model=list[PrivacyRequestPublic])
def list_privacy_requests(user: CurrentUser, db: DBSession) -> list[dict]:
    return privacy_service.list_user_requests(db, user)


@router.get("/requests/{request_id}", response_model=PrivacyRequestDetail)
def get_privacy_request(request_id: uuid.UUID, user: CurrentUser, db: DBSession) -> dict:
    return privacy_service.get_user_request(db, user, request_id)


@router.post("/requests/{request_id}/cancel", response_model=PrivacyRequestPublic)
def cancel_privacy_request(request_id: uuid.UUID, user: CurrentUser, db: DBSession) -> dict:
    return privacy_service.cancel_user_request(db, user, request_id)
