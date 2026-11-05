import uuid
from fastapi import APIRouter, Request, Response, status

from app.api.v1.cookies import clear_session_cookie, set_session_cookie
from app.core.deps import CurrentAuth, CurrentSoftAuth, DBSession
from app.core.rate_limit import limiter
from app.schemas.recovery import (
    RecoverLicenseConfirmRequest,
    RecoverLicenseRequest,
    RecoveryMessage,
)
from app.schemas.auth import (
    ActivateRequest,
    ActivationCodeRequest,
    ActivationResendRequest,
    ActivationStartResponse,
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
)
from app.services import activation_service, auth_service

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.post("/activate", response_model=ActivationStartResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/hour", keys=("ip", "email"), scope="auth.activate")
def activate(
    request: Request,
    payload: ActivateRequest,
    db: DBSession,
) -> dict:
    return activation_service.start_activation(
        db,
        name=payload.name,
        email=payload.email,
        password=payload.password,
        license_code=payload.license_code,
    )


@router.post("/activate/confirm", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", keys=("ip",), scope="auth.activate.confirm")
def confirm_activation(
    request: Request,
    payload: ActivationCodeRequest,
    response: Response,
    db: DBSession,
) -> dict:
    token, data = activation_service.confirm_activation(db, payload.activation_id, payload.code)
    set_session_cookie(response, token)
    return data


@router.post("/activate/resend", response_model=ActivationStartResponse)
@limiter.limit("5/hour", keys=("ip",), scope="auth.activate.resend")
def resend_activation(request: Request, payload: ActivationResendRequest, db: DBSession) -> dict:
    return activation_service.resend_activation(db, payload.activation_id)


@router.post("/recover-license", response_model=RecoveryMessage, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/hour", keys=("ip", "email"), scope="auth.recover_license")
def recover_license(request: Request, payload: RecoverLicenseRequest, db: DBSession) -> dict:
    return activation_service.start_license_recovery(
        db,
        name=payload.name,
        email=payload.email,
        password=payload.password,
    )


@router.post("/recover-license/confirm", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", keys=("ip", "email"), scope="auth.recover_license.confirm")
def confirm_license_recovery(
    request: Request,
    payload: RecoverLicenseConfirmRequest,
    response: Response,
    db: DBSession,
) -> dict:
    token, data = activation_service.confirm_license_recovery(
        db, email=payload.email, code=payload.code
    )
    set_session_cookie(response, token)
    return data


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute", keys=("ip", "email"), scope="auth.login")
def login(request: Request, payload: LoginRequest, response: Response, db: DBSession) -> dict:
    token, data = auth_service.authenticate(db, email=payload.email, password=payload.password)
    set_session_cookie(response, token)
    return data


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(ctx: CurrentSoftAuth, response: Response, db: DBSession) -> Response:
    auth_service.logout(db, ctx.session.id, ctx.user.tenant_id, ctx.user.id)
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=AuthResponse)
def me(ctx: CurrentAuth, db: DBSession) -> dict:
    return auth_service.me_payload(db, ctx.user, ctx.license)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/hour", keys=("ip", "email"), scope="auth.forgot_password")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: DBSession) -> dict:
    token = auth_service.forgot_password(db, email=payload.email)
    return {
        "message": "Se o e-mail estiver cadastrado, enviaremos as instruções de recuperação.",
        "reset_token": token,
    }


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/hour", keys=("ip",), scope="auth.reset_password")
def reset_password(request: Request, payload: ResetPasswordRequest, db: DBSession) -> Response:
    auth_service.reset_password(db, token=payload.token, new_password=payload.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(ctx: CurrentAuth, payload: ChangePasswordRequest, db: DBSession) -> Response:
    auth_service.change_password(
        db,
        user=ctx.user,
        current_session_id=ctx.session.id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions")
def list_sessions(ctx: CurrentAuth, db: DBSession) -> list[dict]:
    return auth_service.list_sessions(db, ctx.user, ctx.session.id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: uuid.UUID, ctx: CurrentAuth, db: DBSession) -> Response:
    auth_service.revoke_session(db, ctx.user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
