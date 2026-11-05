from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from functools import lru_cache
from email.utils import parseaddr
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.log_safety import install_bootstrap_logging_safety

install_bootstrap_logging_safety()

_ALLOWED_ENVIRONMENTS = {"development", "test", "production"}
_PLACEHOLDER_MARKERS = ("troque_", "change_me", "changeme", "example_secret", "your_secret")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "FortexaHome"
    ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    APP_BASE_URL: str = "http://localhost:3010"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str
    MIGRATION_DATABASE_URL: str
    APP_DB_USER: str = "fortexa_app"
    OUTBOX_DB_USER: str = "fortexa_outbox_worker"
    OUTBOX_DB_PASSWORD: str = ""
    OUTBOX_POLL_SECONDS: float = 2.0
    OUTBOX_BATCH_SIZE: int = 10
    OUTBOX_LEASE_SECONDS: int = 60
    OUTBOX_MAX_ATTEMPTS: int = 8
    OUTBOX_RETRY_BASE_SECONDS: float = 5.0
    OUTBOX_RETRY_MAX_SECONDS: float = 900.0
    OUTBOX_DEAD_PAYLOAD_RETENTION_DAYS: int = 30
    OUTBOX_STATUS_LOG_SECONDS: int = 60

    SECRET_KEY: str
    PII_ENCRYPTION_KEY: str
    PII_LOOKUP_KEY: str
    LICENSE_HMAC_KEY: str
    SESSION_COOKIE_NAME: str = "fh_session"
    SESSION_EXPIRE_HOURS: int = 8
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: str = "lax"
    SUPPORT_SESSION_COOKIE_NAME: str = "fh_support_session"
    SUPPORT_SESSION_EXPIRE_HOURS: int = 4
    PASSWORD_RESET_TTL_MINUTES: int = 30
    IDEMPOTENCY_RETENTION_HOURS: int = 168
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_HMAC_KEY: str = ""
    RATE_LIMIT_DB_TIMEOUT_MS: int = 1000
    LOGIN_LOCKOUT_ENABLED: bool = True
    LOGIN_LOCKOUT_FAILURE_THRESHOLD: int = 5
    LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS: int = 60
    LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS: int = 900
    LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS: int = 86400
    LOGIN_LOCKOUT_MAX_TRACKED_FAILURES: int = 32

    CORS_ORIGINS: str = "http://localhost:3010,http://127.0.0.1:3010"
    TRUSTED_PROXY_IPS: str = ""

    DEMO_MODE: bool = False
    ALLOW_PUBLIC_SIGNUP: bool = False
    DEMO_LICENSE_CODE: str = "FH-DEMO-2026"
    DEMO_PRODUCT_SLUG: str = "fortexahome-lifetime"
    DEMO_PRODUCT_PRICE_CENTS: int = 0

    PAYMENT_PROVIDER: str = "hmac_sandbox"
    PAYMENT_WEBHOOK_SECRET: str = ""
    PAYMENT_SANDBOX_ENABLED: bool = False

    HOTMART_ENABLED: bool = False
    HOTMART_WEBHOOK_HOTTOK: str = ""
    HOTMART_PRODUCT_UCODE: str = ""
    HOTMART_PRODUCT_SLUG: str = ""

    HOTMART_RECONCILIATION_ENABLED: bool = False
    HOTMART_RECONCILIATION_CLIENT_ID: str = ""
    HOTMART_RECONCILIATION_CLIENT_SECRET: str = ""
    HOTMART_RECONCILIATION_ENVIRONMENT: str = "production"
    HOTMART_RECONCILIATION_PRODUCT_ID: str = ""
    HOTMART_RECONCILIATION_TIMEOUT_SECONDS: float = 10.0
    HOTMART_RECONCILIATION_MAX_TRANSACTIONS: int = 25
    HOTMART_RECONCILIATION_LOOKBACK_HOURS: int = 72
    HOTMART_RECONCILIATION_MAX_ATTEMPTS: int = 3
    HOTMART_RECONCILIATION_BACKOFF_BASE_SECONDS: float = 1.0
    HOTMART_RECONCILIATION_REQUEST_INTERVAL_SECONDS: float = 0.25

    EMAIL_PROVIDER: str = "dev"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "FortexaHome <nao-responda@fortexahome.local>"
    EMAIL_VERIFICATION_HMAC_KEY: str = ""

    TEST_POSTGRES_DB: str = "fortexahome_test"

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def trusted_proxy_ips_list(self) -> list[str]:
        return [item.strip() for item in self.TRUSTED_PROXY_IPS.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    @property
    def pii_encryption_bytes(self) -> bytes:
        try:
            raw = base64.b64decode(self.PII_ENCRYPTION_KEY, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("PII_ENCRYPTION_KEY deve ser base64 válido") from exc
        if len(raw) != 32:
            raise ValueError("PII_ENCRYPTION_KEY deve ter 32 bytes")
        return raw

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.ENV.lower() not in _ALLOWED_ENVIRONMENTS:
            raise ValueError("ENV deve ser development, test ou production")
        if self.SESSION_COOKIE_SAMESITE.lower() not in {"lax", "strict", "none"}:
            raise ValueError("SESSION_COOKIE_SAMESITE deve ser lax, strict ou none")
        if len(self.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY deve ter pelo menos 32 caracteres")
        if len(self.PII_LOOKUP_KEY) < 32:
            raise ValueError("PII_LOOKUP_KEY deve ter pelo menos 32 caracteres")
        if len(self.LICENSE_HMAC_KEY) < 32:
            raise ValueError("LICENSE_HMAC_KEY deve ter pelo menos 32 caracteres")
        self.pii_encryption_bytes
        if not 1 <= self.IDEMPOTENCY_RETENTION_HOURS <= 720:
            raise ValueError("IDEMPOTENCY_RETENTION_HOURS deve estar entre 1 e 720")
        if self.OUTBOX_POLL_SECONDS <= 0 or self.OUTBOX_BATCH_SIZE <= 0 or self.OUTBOX_LEASE_SECONDS <= 0:
            raise ValueError("As configurações de polling, lote e lease da outbox devem ser positivas")
        if self.OUTBOX_MAX_ATTEMPTS <= 0 or self.OUTBOX_RETRY_BASE_SECONDS <= 0:
            raise ValueError("As tentativas e o backoff inicial da outbox devem ser positivos")
        if self.OUTBOX_DEAD_PAYLOAD_RETENTION_DAYS <= 0:
            raise ValueError("OUTBOX_DEAD_PAYLOAD_RETENTION_DAYS deve ser positivo")
        if self.OUTBOX_STATUS_LOG_SECONDS <= 0:
            raise ValueError("OUTBOX_STATUS_LOG_SECONDS deve ser positivo")
        if self.OUTBOX_RETRY_MAX_SECONDS < self.OUTBOX_RETRY_BASE_SECONDS:
            raise ValueError("OUTBOX_RETRY_MAX_SECONDS deve ser maior ou igual ao backoff inicial")
        if self.RATE_LIMIT_DB_TIMEOUT_MS < 100 or self.RATE_LIMIT_DB_TIMEOUT_MS > 5000:
            raise ValueError("RATE_LIMIT_DB_TIMEOUT_MS deve estar entre 100 e 5000")
        if not 2 <= self.LOGIN_LOCKOUT_FAILURE_THRESHOLD <= 20:
            raise ValueError("LOGIN_LOCKOUT_FAILURE_THRESHOLD deve estar entre 2 e 20")
        if not 1 <= self.LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS <= 600:
            raise ValueError("LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS deve estar entre 1 e 600")
        if not (
            self.LOGIN_LOCKOUT_BASE_COOLDOWN_SECONDS
            <= self.LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS
            <= 3600
        ):
            raise ValueError(
                "LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS deve estar entre o cooldown base e 3600"
            )
        if not (
            self.LOGIN_LOCKOUT_MAX_COOLDOWN_SECONDS
            <= self.LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS
            <= 604800
        ):
            raise ValueError(
                "LOGIN_LOCKOUT_INACTIVITY_RESET_SECONDS deve estar entre o cooldown máximo e 7 dias"
            )
        if not (
            self.LOGIN_LOCKOUT_FAILURE_THRESHOLD
            <= self.LOGIN_LOCKOUT_MAX_TRACKED_FAILURES
            <= 100
        ):
            raise ValueError(
                "LOGIN_LOCKOUT_MAX_TRACKED_FAILURES deve estar entre o limiar e 100"
            )
        if self.HOTMART_RECONCILIATION_ENVIRONMENT.lower() not in {"production", "sandbox"}:
            raise ValueError("HOTMART_RECONCILIATION_ENVIRONMENT deve ser production ou sandbox")
        if not 1 <= self.HOTMART_RECONCILIATION_TIMEOUT_SECONDS <= 30:
            raise ValueError("HOTMART_RECONCILIATION_TIMEOUT_SECONDS deve estar entre 1 e 30")
        if not 1 <= self.HOTMART_RECONCILIATION_MAX_TRANSACTIONS <= 100:
            raise ValueError("HOTMART_RECONCILIATION_MAX_TRANSACTIONS deve estar entre 1 e 100")
        if not 1 <= self.HOTMART_RECONCILIATION_LOOKBACK_HOURS <= 720:
            raise ValueError("HOTMART_RECONCILIATION_LOOKBACK_HOURS deve estar entre 1 e 720")
        if not 1 <= self.HOTMART_RECONCILIATION_MAX_ATTEMPTS <= 5:
            raise ValueError("HOTMART_RECONCILIATION_MAX_ATTEMPTS deve estar entre 1 e 5")
        if not 0.1 <= self.HOTMART_RECONCILIATION_BACKOFF_BASE_SECONDS <= 30:
            raise ValueError("HOTMART_RECONCILIATION_BACKOFF_BASE_SECONDS deve estar entre 0.1 e 30")
        if not 0 <= self.HOTMART_RECONCILIATION_REQUEST_INTERVAL_SECONDS <= 5:
            raise ValueError("HOTMART_RECONCILIATION_REQUEST_INTERVAL_SECONDS deve estar entre 0 e 5")
        product_id = self.HOTMART_RECONCILIATION_PRODUCT_ID.strip()
        if product_id and not re.fullmatch(r"\d{1,12}", product_id):
            raise ValueError("HOTMART_RECONCILIATION_PRODUCT_ID deve conter apenas dígitos")

        if self.PAYMENT_SANDBOX_ENABLED and len(self.PAYMENT_WEBHOOK_SECRET) < 32:
            raise ValueError(
                "PAYMENT_WEBHOOK_SECRET deve ter pelo menos 32 caracteres quando PAYMENT_SANDBOX_ENABLED=true"
            )

        if self.is_production:
            if self.DEBUG:
                raise ValueError("DEBUG deve ser false em produção")
            if self.LOG_LEVEL.upper() == "DEBUG":
                raise ValueError("LOG_LEVEL não pode ser DEBUG em produção")
            if not self.SESSION_COOKIE_SECURE:
                raise ValueError("SESSION_COOKIE_SECURE deve ser true em produção")
            if self.SESSION_COOKIE_SAMESITE.lower() not in {"lax", "strict"}:
                raise ValueError("SESSION_COOKIE_SAMESITE não pode ser none em produção")
            parsed_base_url = urlsplit(self.APP_BASE_URL)
            if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
                raise ValueError("APP_BASE_URL deve ser uma URL HTTPS completa em produção")
            for name in (
                "SECRET_KEY",
                "PII_ENCRYPTION_KEY",
                "PII_LOOKUP_KEY",
                "LICENSE_HMAC_KEY",
                "EMAIL_VERIFICATION_HMAC_KEY",
                "RATE_LIMIT_HMAC_KEY",
                "OUTBOX_DB_PASSWORD",
                "RESEND_API_KEY",
                "HOTMART_WEBHOOK_HOTTOK",
            ):
                value = str(getattr(self, name)).strip().lower()
                if value.startswith(_PLACEHOLDER_MARKERS):
                    raise ValueError(f"{name} não pode conter um placeholder de exemplo em produção")
            if self.DEMO_MODE:
                raise ValueError("DEMO_MODE deve ser false em produção")
            if self.ALLOW_PUBLIC_SIGNUP:
                raise ValueError("Cadastro público não é permitido nesta versão comercial")
            if self.PAYMENT_SANDBOX_ENABLED:
                raise ValueError("PAYMENT_SANDBOX_ENABLED deve ser false em produção")
            if self.EMAIL_PROVIDER != "resend":
                raise ValueError("EMAIL_PROVIDER deve ser resend em produção")
            if len(self.EMAIL_VERIFICATION_HMAC_KEY) < 32:
                raise ValueError("EMAIL_VERIFICATION_HMAC_KEY deve ter pelo menos 32 caracteres")
            if self.EMAIL_VERIFICATION_HMAC_KEY in {
                self.SECRET_KEY,
                self.PII_LOOKUP_KEY,
                self.LICENSE_HMAC_KEY,
            }:
                raise ValueError("EMAIL_VERIFICATION_HMAC_KEY deve ser dedicada a esta finalidade")
            if len(self.RATE_LIMIT_HMAC_KEY) < 32:
                raise ValueError("RATE_LIMIT_HMAC_KEY deve ter pelo menos 32 caracteres em produção")
            if self.RATE_LIMIT_HMAC_KEY in {
                self.SECRET_KEY,
                self.PII_LOOKUP_KEY,
                self.LICENSE_HMAC_KEY,
                self.EMAIL_VERIFICATION_HMAC_KEY,
            }:
                raise ValueError("RATE_LIMIT_HMAC_KEY deve ser dedicada a esta finalidade")
            if not self.RESEND_API_KEY.strip():
                raise ValueError("RESEND_API_KEY deve estar configurada em produção")
            if self.HOTMART_ENABLED:
                if len(self.HOTMART_WEBHOOK_HOTTOK.strip()) < 16:
                    raise ValueError("HOTMART_WEBHOOK_HOTTOK deve estar configurado quando Hotmart estiver habilitado")
                if not self.HOTMART_PRODUCT_UCODE.strip():
                    raise ValueError("HOTMART_PRODUCT_UCODE deve estar configurado quando Hotmart estiver habilitado")
                if not self.HOTMART_PRODUCT_SLUG.strip():
                    raise ValueError("HOTMART_PRODUCT_SLUG deve mapear o produto Hotmart a um produto interno")
            if len(self.OUTBOX_DB_PASSWORD) < 32:
                raise ValueError("OUTBOX_DB_PASSWORD deve ter pelo menos 32 caracteres em produção")
            if self.OUTBOX_DB_USER == self.APP_DB_USER:
                raise ValueError("OUTBOX_DB_USER deve ser separado de APP_DB_USER")
            _, from_address = parseaddr(self.EMAIL_FROM)
            try:
                sender = validate_email(from_address, check_deliverability=False)
            except EmailNotValidError as exc:
                raise ValueError("EMAIL_FROM deve conter um remetente de e-mail válido") from exc
            if "." not in sender.domain or sender.domain.endswith(".local"):
                raise ValueError("EMAIL_FROM deve conter um remetente válido com domínio público")
            for proxy in self.trusted_proxy_ips_list:
                try:
                    ipaddress.ip_network(proxy, strict=False)
                except ValueError as exc:
                    raise ValueError("TRUSTED_PROXY_IPS deve conter IPs ou redes válidos") from exc
            for origin in self.cors_origins_list:
                parsed = urlsplit(origin)
                if parsed.scheme != "https" or not parsed.netloc:
                    raise ValueError("CORS_ORIGINS deve conter apenas origens HTTPS em produção")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
