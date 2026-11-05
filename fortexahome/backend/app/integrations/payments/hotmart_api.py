"""Minimal Hotmart Sales API client used only by commercial reconciliation."""
from __future__ import annotations

import base64
import math
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

_AUTH_BASES = {
    "production": "https://api-sec-vlc.hotmart.com/security/oauth/token",
    "sandbox": "https://sandbox.hotmart.com/security/oauth/token",
}
_API_BASES = {
    "production": "https://developers.hotmart.com/payments/api/v1",
    "sandbox": "https://sandbox.hotmart.com/payments/api/v1",
}
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class HotmartApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "hotmart_api_error",
        http_status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after = retry_after


class HotmartAuthError(HotmartApiError):
    pass


class HotmartNotFoundError(HotmartApiError):
    pass


class HotmartRateLimitError(HotmartApiError):
    pass


class HotmartTransientError(HotmartApiError):
    pass


class HotmartResponseError(HotmartApiError):
    pass


@dataclass(frozen=True)
class HotmartApiConfig:
    client_id: str
    client_secret: str
    environment: str
    timeout_seconds: float
    max_attempts: int
    backoff_base_seconds: float

    @property
    def auth_url(self) -> str:
        return _AUTH_BASES[self.environment.lower()]

    @property
    def api_base_url(self) -> str:
        return _API_BASES[self.environment.lower()]


@dataclass(frozen=True)
class HotmartTransactionObservation:
    transaction: str
    status: str
    product_id: int | None
    product_name: str | None
    product_ucode: str | None
    order_date: datetime | None
    approved_date: datetime | None
    price_cents: int | None
    price_currency: str | None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _price_cents(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return None


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            target = parsedate_to_datetime(raw)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "hotmart_api_error"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()[:80]
    return "hotmart_api_error"


class HotmartApiClient:
    def __init__(
        self,
        config: HotmartApiConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self._owns_client = client is None
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "HotmartApiClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            delay = retry_after
        else:
            base = self.config.backoff_base_seconds * (2 ** max(0, attempt))
            delay = min(30.0, base) + self._rng.uniform(0, min(0.5, base))
        self._sleep(max(0.0, delay))

    def _invalidate_token(self) -> None:
        self._token = None
        self._token_expires_at = 0.0

    def _fetch_token(self) -> str:
        if not self.config.client_id.strip() or not self.config.client_secret.strip():
            raise HotmartAuthError(
                "Credenciais da API Hotmart não configuradas",
                code="missing_credentials",
            )
        if self._token and time.monotonic() < self._token_expires_at - 30:
            return self._token
        with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at - 30:
                return self._token
            basic = base64.b64encode(
                f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
            ).decode("ascii")
            headers = {
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            params = {
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            }
            last_error: HotmartApiError | None = None
            for attempt in range(self.config.max_attempts):
                try:
                    response = self._client.post(
                        self.config.auth_url,
                        params=params,
                        headers=headers,
                        content=b"",
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = HotmartTransientError(
                        "Falha de rede ao obter token da Hotmart",
                        code="auth_network_error",
                        retryable=True,
                    )
                    if attempt + 1 < self.config.max_attempts:
                        self._backoff(attempt, None)
                        continue
                    raise last_error from exc

                if response.status_code in {401, 403}:
                    raise HotmartAuthError(
                        "Credenciais da reconciliação Hotmart recusadas",
                        code=_error_code(response),
                        http_status=response.status_code,
                    )
                if response.status_code == 429:
                    retry_after = _retry_after(response)
                    if attempt + 1 < self.config.max_attempts:
                        self._backoff(attempt, retry_after)
                        continue
                    raise HotmartRateLimitError(
                        "Rate limit da Hotmart excedido ao obter token",
                        code="too_many_requests",
                        http_status=429,
                        retryable=True,
                        retry_after=retry_after,
                    )
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = HotmartTransientError(
                        "Hotmart indisponível ao obter token",
                        code=_error_code(response),
                        http_status=response.status_code,
                        retryable=True,
                    )
                    if attempt + 1 < self.config.max_attempts:
                        self._backoff(attempt, _retry_after(response))
                        continue
                    raise last_error
                if response.status_code != 200:
                    raise HotmartResponseError(
                        "Falha inesperada ao obter token da Hotmart",
                        code=_error_code(response),
                        http_status=response.status_code,
                    )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise HotmartResponseError(
                        "Resposta inválida ao obter token da Hotmart",
                        code="malformed_token_response",
                        http_status=200,
                    ) from exc
                token = payload.get("access_token") if isinstance(payload, dict) else None
                expires_in = payload.get("expires_in") if isinstance(payload, dict) else None
                if not isinstance(token, str) or not token.strip():
                    raise HotmartResponseError(
                        "Token ausente na resposta da Hotmart",
                        code="missing_access_token",
                        http_status=200,
                    )
                try:
                    expires = float(expires_in)
                except (TypeError, ValueError):
                    expires = 300.0
                self._token = token.strip()
                self._token_expires_at = time.monotonic() + max(30.0, expires)
                return self._token
            raise last_error or HotmartTransientError("Falha ao obter token da Hotmart")

    def _get_json(self, path: str, params: dict) -> dict:
        last_error: HotmartApiError | None = None
        refreshed = False
        attempt = 0
        while True:
            token = self._fetch_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                response = self._client.get(
                    f"{self.config.api_base_url}{path}",
                    params=params,
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = HotmartTransientError(
                    "Falha de rede na API Hotmart",
                    code="network_error",
                    retryable=True,
                )
                if attempt + 1 < self.config.max_attempts:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise last_error from exc

            if response.status_code == 401 and not refreshed:
                self._invalidate_token()
                refreshed = True
                continue
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise HotmartResponseError(
                        "Resposta malformada da API Hotmart",
                        code="malformed_json",
                        http_status=200,
                    ) from exc
                if not isinstance(payload, dict):
                    raise HotmartResponseError(
                        "Resposta inesperada da API Hotmart",
                        code="unexpected_response",
                        http_status=200,
                    )
                return payload
            if response.status_code == 401:
                raise HotmartAuthError(
                    "Token da Hotmart recusado após renovação",
                    code=_error_code(response),
                    http_status=401,
                )
            if response.status_code == 403:
                raise HotmartAuthError(
                    "Aplicação sem permissão para consultar vendas",
                    code=_error_code(response),
                    http_status=403,
                )
            if response.status_code == 404:
                raise HotmartNotFoundError(
                    "Recurso Hotmart não encontrado",
                    code=_error_code(response),
                    http_status=404,
                )
            if response.status_code == 429:
                retry_after = _retry_after(response)
                last_error = HotmartRateLimitError(
                    "Rate limit da Hotmart excedido",
                    code="too_many_requests",
                    http_status=429,
                    retryable=True,
                    retry_after=retry_after,
                )
                if attempt + 1 < self.config.max_attempts:
                    self._backoff(attempt, retry_after)
                    attempt += 1
                    continue
                raise last_error
            if response.status_code in _RETRYABLE_STATUS:
                last_error = HotmartTransientError(
                    "API Hotmart temporariamente indisponível",
                    code=_error_code(response),
                    http_status=response.status_code,
                    retryable=True,
                )
                if attempt + 1 < self.config.max_attempts:
                    self._backoff(attempt, _retry_after(response))
                    attempt += 1
                    continue
                raise last_error
            raise HotmartResponseError(
                "Requisição recusada pela API Hotmart",
                code=_error_code(response),
                http_status=response.status_code,
            )

    def fetch_transaction(self, transaction: str) -> HotmartTransactionObservation | None:
        transaction = transaction.strip()
        if not transaction:
            raise ValueError("transaction não pode ser vazia")
        payload = self._get_json(
            "/sales/history",
            {"transaction": transaction, "max_results": 5},
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise HotmartResponseError(
                "Lista de vendas ausente na resposta da Hotmart",
                code="missing_items",
            )
        matches: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            purchase = item.get("purchase")
            if isinstance(purchase, dict) and str(purchase.get("transaction", "")).strip() == transaction:
                matches.append(item)
        if not matches:
            return None
        statuses = {
            str((item.get("purchase") or {}).get("status", "")).strip().upper()
            for item in matches
        }
        statuses.discard("")
        if len(statuses) > 1:
            raise HotmartResponseError(
                "A Hotmart retornou estados conflitantes para a mesma transação",
                code="multiple_transaction_states",
            )
        item = matches[0]
        purchase = item.get("purchase") or {}
        product = item.get("product") or {}
        status = str(purchase.get("status", "")).strip().upper()
        if not status:
            raise HotmartResponseError("Status ausente na transação Hotmart", code="missing_status")
        product_id = product.get("id")
        try:
            product_id = int(product_id) if product_id is not None else None
        except (TypeError, ValueError):
            product_id = None
        price = purchase.get("price") if isinstance(purchase.get("price"), dict) else {}
        return HotmartTransactionObservation(
            transaction=transaction,
            status=status,
            product_id=product_id,
            product_name=str(product.get("name")) if product.get("name") is not None else None,
            product_ucode=str(product.get("ucode")) if product.get("ucode") is not None else None,
            order_date=_timestamp(purchase.get("order_date")),
            approved_date=_timestamp(purchase.get("approved_date")),
            price_cents=_price_cents(price.get("value")),
            price_currency=(
                str(price.get("currency_code")).strip().upper()
                if price.get("currency_code")
                else None
            ),
        )
