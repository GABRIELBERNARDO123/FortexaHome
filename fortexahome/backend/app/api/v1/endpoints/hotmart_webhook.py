import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.deps import DBSession
from app.core.rate_limit import limiter
from app.integrations.payments.hotmart import authenticate_hottok, parse_payload
from app.services import license_service

logger = logging.getLogger("fortexahome.webhooks.hotmart")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_MAX_BODY_BYTES = 256 * 1024


@router.post("/hotmart", status_code=status.HTTP_200_OK)
@limiter.limit("60/minute", keys=("ip",), scope="webhooks.hotmart")
async def hotmart_webhook(request: Request, db: DBSession) -> dict[str, str]:
    settings = get_settings()
    if not settings.HOTMART_ENABLED or not settings.HOTMART_PRODUCT_UCODE or not settings.HOTMART_PRODUCT_SLUG:
        raise HTTPException(status_code=503, detail="Webhook indisponível")
    if not authenticate_hottok(request.headers.get("x-hotmart-hottok")):
        raise HTTPException(status_code=401, detail="Notificação não autorizada")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="Tipo de conteúdo inválido")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Notificação muito grande")
        except ValueError:
            raise HTTPException(status_code=400, detail="Notificação inválida") from None

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Notificação muito grande")
        chunks.append(chunk)
    raw_body = b"".join(chunks)
    try:
        payload = parse_payload(raw_body)
    except (ValidationError, ValueError, UnicodeDecodeError):
        logger.warning("Webhook Hotmart inválido")
        raise HTTPException(status_code=400, detail="Notificação inválida") from None

    if payload.data.product.ucode != settings.HOTMART_PRODUCT_UCODE:
        logger.info("Webhook Hotmart ignorado: produto não configurado")
        return {"status": "ignored"}

    try:
        return license_service.process_hotmart_event(
            db, payload, payload_hash=hashlib.sha256(raw_body).hexdigest()
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Falha ao processar evento Hotmart error_type=%s",
            type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=503, detail="Notificação não processada") from None
