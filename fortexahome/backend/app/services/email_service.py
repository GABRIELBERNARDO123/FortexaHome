"""Email rendering and provider adapter. Called by the outbox worker only."""
from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("fortexahome.email")
settings = get_settings()


class PermanentEmailDeliveryError(Exception):
    pass


class TransientEmailDeliveryError(Exception):
    pass


def render_message(event_type: str, payload: dict[str, str]) -> tuple[str, str, str]:
    recipient = payload["to"]
    if event_type == "activation_verification":
        code = payload["code"]
        subject = "FortexaHome — confirme seu e-mail"
        body = (
            "Você iniciou a ativação de uma conta FortexaHome.\n\n"
            f"Seu código de verificação é: {code}\n"
            "Ele é válido por 10 minutos e só pode ser usado uma vez. Não compartilhe este código.\n\n"
            "Se você não solicitou esta ativação, ignore esta mensagem. "
            "Nenhuma conta será criada sem a confirmação."
        )
    elif event_type == "password_reset":
        link = f"{settings.APP_BASE_URL}/redefinir-senha?token={payload['token']}"
        subject = "FortexaHome — redefinição de senha"
        body = (
            "Recebemos um pedido para redefinir sua senha do FortexaHome.\n\n"
            f"Use este link em até {settings.PASSWORD_RESET_TTL_MINUTES} minutos:\n{link}\n\n"
            "Se você não fez esse pedido, ignore esta mensagem."
        )
    elif event_type == "license_delivery":
        subject = "FortexaHome — sua licença de acesso"
        body = (
            f"Obrigado por adquirir {payload['product_name']}.\n\n"
            f"Seu código de ativação é: {payload['code']}\n\n"
            f"Acesse {settings.APP_BASE_URL}/entrar, escolha “Ativar licença” e crie sua conta com este código. "
            "Cada licença pode ser vinculada a uma única conta."
        )
    elif event_type == "license_recovery_instructions":
        subject = "FortexaHome — como recuperar seu acesso"
        body = (
            f"Recebemos uma solicitação de suporte sobre {payload['product_name']}.\n\n"
            f"Acesse {settings.APP_BASE_URL}/entrar e escolha “Recuperar acesso”.\n"
            "Informe o e-mail usado na compra. Se você ainda não ativou a licença, "
            "receberá um código para concluir a ativação. Se sua conta já existe, "
            "use a opção “Esqueci minha senha”.\n\n"
            "Se você não solicitou este contato, ignore esta mensagem."
        )
    else:
        raise PermanentEmailDeliveryError("unsupported_event")
    return recipient, subject, body


def send_rendered_email(to: str, subject: str, text: str, *, idempotency_key: str) -> str | None:
    if settings.EMAIL_PROVIDER == "resend" and settings.RESEND_API_KEY:
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Idempotency-Key": idempotency_key,
                },
                json={"from": settings.EMAIL_FROM, "to": [to], "subject": subject, "text": text},
                timeout=10,
            )
            if response.status_code >= 400:
                if response.status_code == 409:
                    # Resend distinguishes a safe concurrent retry from a key
                    # reused with a different request. Never log the body.
                    try:
                        error_body = response.json()
                    except (ValueError, AttributeError):
                        error_body = {}
                    error_code = (
                        error_body.get("name") or error_body.get("code") or error_body.get("type")
                        if isinstance(error_body, dict) else None
                    )
                    if error_code == "concurrent_idempotent_requests":
                        raise TransientEmailDeliveryError("provider_transient")
                    raise PermanentEmailDeliveryError("idempotency_conflict")
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    raise TransientEmailDeliveryError("provider_transient")
                raise PermanentEmailDeliveryError("provider_rejected")
            try:
                return response.json().get("id")
            except (ValueError, AttributeError):
                return None
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransientEmailDeliveryError("provider_unavailable") from exc
    if settings.EMAIL_PROVIDER == "dev" and not settings.is_production:
        # Development sink deliberately does not log recipients or message content.
        return "development-sink"
    raise PermanentEmailDeliveryError("provider_not_configured")
