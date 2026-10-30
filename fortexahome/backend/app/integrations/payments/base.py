from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaymentNotification:
    event_id: str
    event_type: str
    external_order_id: str
    product_slug: str
    buyer_email: str
    amount_cents: int
    currency: str
    customer_id: str | None = None


class PaymentProvider(Protocol):
    """
    Contrato para integração segura com uma plataforma de pagamentos.

    Implementações reais devem:
    - validar assinatura/segredo do provedor sobre o corpo bruto;
    - recusar notificações não autenticadas;
    - mapear o evento para PaymentNotification;
    - jamais confiar em dados de compra enviados pelo navegador.
    """

    name: str

    def verify_and_parse(self, raw_body: bytes, signature: str | None) -> PaymentNotification | None:
        ...
