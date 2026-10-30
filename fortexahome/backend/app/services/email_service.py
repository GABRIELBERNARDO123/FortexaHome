from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("fortexahome.email")
settings = get_settings()


def send_email(to: str, subject: str, text: str) -> None:
    if settings.EMAIL_PROVIDER == "resend" and settings.RESEND_API_KEY:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={"from": settings.EMAIL_FROM, "to": [to], "subject": subject, "text": text},
            timeout=10,
        )
        response.raise_for_status()
        return

    if settings.is_production:
        logger.error("Provedor de e-mail não configurado em produção")
        return
    logger.info("E-mail de desenvolvimento gerado: %s", subject)


def send_password_reset(to: str, token: str) -> None:
    link = f"{settings.APP_BASE_URL}/redefinir-senha?token={token}"
    send_email(
        to,
        "FortexaHome — redefinição de senha",
        (
            "Recebemos um pedido para redefinir sua senha do FortexaHome.\n\n"
            f"Use este link em até {settings.PASSWORD_RESET_TTL_MINUTES} minutos:\n{link}\n\n"
            "Se você não fez esse pedido, ignore esta mensagem."
        ),
    )


def send_license_delivery(to: str, code: str, product_name: str) -> None:
    send_email(
        to,
        "FortexaHome — sua licença de acesso",
        (
            f"Obrigado por adquirir {product_name}.\n\n"
            f"Seu código de ativação é: {code}\n\n"
            "Acesse o FortexaHome, escolha “Ativar licença” e crie sua conta com este código. "
            "Cada licença pode ser vinculada a uma única conta."
        ),
    )
