import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.core.deps import DBSession
from app.core.rate_limit import limiter
from app.integrations.payments.hmac_sandbox import HmacSandboxProvider
from app.services import license_service

logger = logging.getLogger("fortexahome.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_PROVIDERS = {
    "hmac_sandbox": HmacSandboxProvider(),
}


def sandbox_routes_enabled() -> bool:
    settings = get_settings()
    return settings.PAYMENT_SANDBOX_ENABLED and not settings.is_production


@router.post("/payments/{provider}", status_code=status.HTTP_200_OK)
@limiter.limit("120/minute", keys=("ip",), scope="webhooks.payment")
async def payment_webhook(provider: str, request: Request, db: DBSession) -> dict:
    implementation = _PROVIDERS.get(provider)
    if implementation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provedor de pagamento desconhecido")

    raw_body = await request.body()
    signature = request.headers.get("x-fortexa-signature")
    try:
        notification = implementation.verify_and_parse(raw_body, signature)
    except (ValueError, TypeError, UnicodeDecodeError, KeyError):
        logger.warning("Webhook inválido recebido do provedor %s", provider)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Notificação inválida") from None
    if notification is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura inválida")

    payload_hash = hashlib.sha256(raw_body).hexdigest()
    return license_service.process_payment_notification(
        db, notification, provider=provider, payload_hash=payload_hash
    )
