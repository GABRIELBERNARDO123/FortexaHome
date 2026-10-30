from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    SECRET_KEY: str
    PII_ENCRYPTION_KEY: str
    PII_LOOKUP_KEY: str
    LICENSE_HMAC_KEY: str
    SESSION_COOKIE_NAME: str = "fh_session"
    SESSION_EXPIRE_HOURS: int = 8
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: str = "lax"
    PASSWORD_RESET_TTL_MINUTES: int = 30
    RATE_LIMIT_ENABLED: bool = True

    CORS_ORIGINS: str = "http://localhost:3010,http://127.0.0.1:3010"
    TRUSTED_PROXY_IPS: str = ""

    DEMO_MODE: bool = False
    ALLOW_PUBLIC_SIGNUP: bool = False
    DEMO_LICENSE_CODE: str = "FH-DEMO-2026"
    DEMO_PRODUCT_SLUG: str = "fortexahome-lifetime"
    DEMO_PRODUCT_PRICE_CENTS: int = 0

    PAYMENT_PROVIDER: str = "hmac_sandbox"
    PAYMENT_WEBHOOK_SECRET: str = ""

    EMAIL_PROVIDER: str = "dev"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "FortexaHome <nao-responda@fortexahome.local>"

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
        if len(self.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY deve ter pelo menos 32 caracteres")
        if len(self.PII_LOOKUP_KEY) < 32:
            raise ValueError("PII_LOOKUP_KEY deve ter pelo menos 32 caracteres")
        if len(self.LICENSE_HMAC_KEY) < 32:
            raise ValueError("LICENSE_HMAC_KEY deve ter pelo menos 32 caracteres")
        self.pii_encryption_bytes

        if self.is_production:
            if self.DEBUG:
                raise ValueError("DEBUG deve ser false em produção")
            if not self.SESSION_COOKIE_SECURE:
                raise ValueError("SESSION_COOKIE_SECURE deve ser true em produção")
            if self.DEMO_MODE:
                raise ValueError("DEMO_MODE deve ser false em produção")
            if self.ALLOW_PUBLIC_SIGNUP:
                raise ValueError("Cadastro público não é permitido nesta versão comercial")
            if not self.PAYMENT_WEBHOOK_SECRET or len(self.PAYMENT_WEBHOOK_SECRET) < 32:
                raise ValueError("PAYMENT_WEBHOOK_SECRET deve estar configurado em produção")
            for origin in self.cors_origins_list:
                parsed = urlsplit(origin)
                if parsed.scheme != "https" or not parsed.netloc:
                    raise ValueError("CORS_ORIGINS deve conter apenas origens HTTPS em produção")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
