from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.preflight import (
    environment_checks,
    failures,
    validation_error_results,
    worker_environment_checks,
)


def base_values(**overrides):
    values = {
        "ENV": "test",
        "DEBUG": "true",
        "DATABASE_URL": "postgresql+psycopg://app:app-password@localhost:5432/fortexahome_test",
        "MIGRATION_DATABASE_URL": "postgresql+psycopg://owner:owner-password@localhost:5432/fortexahome_test",
        "APP_DB_USER": "app",
        "OUTBOX_DB_USER": "worker",
        "OUTBOX_DB_PASSWORD": "worker-password-with-enough-length-000000",
        "SECRET_KEY": "s" * 48,
        "PII_ENCRYPTION_KEY": base64.b64encode(b"a" * 32).decode(),
        "PII_LOOKUP_KEY": "l" * 48,
        "LICENSE_HMAC_KEY": "h" * 48,
        "EMAIL_VERIFICATION_HMAC_KEY": "e" * 48,
        "RATE_LIMIT_HMAC_KEY": "r" * 48,
        "EMAIL_PROVIDER": "dev",
        "EMAIL_FROM": "Fortexa <hello@example.com>",
        "APP_BASE_URL": "http://localhost:3010",
        "CORS_ORIGINS": "http://localhost:3010",
        "TRUSTED_PROXY_IPS": "172.31.0.10",
        "HOTMART_ENABLED": "false",
    }
    values.update(overrides)
    return values


def production_values(**overrides):
    values = base_values(
        ENV="production",
        DEBUG="false",
        SESSION_COOKIE_SECURE="true",
        SESSION_COOKIE_SAMESITE="lax",
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="resend-key",
        EMAIL_FROM="Fortexa <hello@example.com>",
        APP_BASE_URL="https://app.example.com",
        CORS_ORIGINS="https://app.example.com",
        PAYMENT_PROVIDER="hotmart",
        PAYMENT_SANDBOX_ENABLED="false",
        RATE_LIMIT_ENABLED="true",
    )
    values.update(overrides)
    return values


def codes(results):
    return {item.code for item in failures(results)}


def test_environment_checks_accepts_valid_production_configuration():
    settings = Settings(**production_values())
    results = environment_checks(settings)
    assert not failures(results)
    assert any(item.code == "config.hotmart" and item.level == "SKIP" for item in results)


def test_environment_checks_requires_email_verification_key_in_all_environments():
    settings = Settings(**base_values(EMAIL_VERIFICATION_HMAC_KEY=""))
    assert "config.EMAIL_VERIFICATION_HMAC_KEY" in codes(environment_checks(settings))


def test_environment_checks_requires_outbox_password_in_all_environments():
    settings = Settings(**base_values(OUTBOX_DB_PASSWORD=""))
    assert "config.OUTBOX_DB_PASSWORD" in codes(environment_checks(settings))


def test_environment_checks_rejects_hotmart_without_credentials_when_enabled():
    settings = Settings(**base_values(HOTMART_ENABLED="true"))
    assert {
        "config.HOTMART_WEBHOOK_HOTTOK",
        "config.HOTMART_PRODUCT_UCODE",
        "config.HOTMART_PRODUCT_SLUG",
    } <= codes(environment_checks(settings))


def test_environment_checks_does_not_require_hotmart_when_disabled():
    settings = Settings(**base_values(HOTMART_ENABLED="false"))
    results = environment_checks(settings)
    assert "config.HOTMART_WEBHOOK_HOTTOK" not in codes(results)
    assert "config.HOTMART_PRODUCT_UCODE" not in codes(results)
    assert "config.HOTMART_PRODUCT_SLUG" not in codes(results)


def test_environment_checks_rejects_rate_limit_disabled_in_production():
    settings = Settings(**production_values(RATE_LIMIT_ENABLED="false"))
    assert "config.RATE_LIMIT_ENABLED" in codes(environment_checks(settings))


def test_environment_checks_rejects_shared_secret_purposes_in_production():
    settings = Settings(**production_values(LICENSE_HMAC_KEY="s" * 48))
    assert "config.secret_purposes" in codes(environment_checks(settings))


def test_environment_checks_requires_dedicated_rate_limit_key_in_production():
    with pytest.raises(ValidationError):
        Settings(**production_values(RATE_LIMIT_HMAC_KEY=""))


def test_environment_checks_rejects_worker_password_equal_to_app_password():
    password = "same-password-with-enough-length-0000000000"
    settings = Settings(
        **production_values(
            DATABASE_URL=f"postgresql+psycopg://app:{password}@localhost:5432/fortexahome_test",
            OUTBOX_DB_PASSWORD=password,
        )
    )
    assert "config.role_passwords" in codes(environment_checks(settings))


def test_environment_checks_rejects_app_base_url_without_https_in_production():
    with pytest.raises(ValidationError):
        Settings(**production_values(APP_BASE_URL="http://app.example.com"))


def test_environment_checks_rejects_samesite_none_in_production():
    with pytest.raises(ValidationError):
        Settings(**production_values(SESSION_COOKIE_SAMESITE="none"))


def test_validation_errors_do_not_include_secret_values():
    secret = "troque_este_segredo_super_secreto_123456789"
    with pytest.raises(ValidationError) as error:
        Settings(**production_values(SECRET_KEY=secret))
    rendered = " ".join(item.message for item in validation_error_results(error.value))
    assert secret not in rendered
    assert "placeholder" in rendered.lower()


def test_worker_environment_checks_requires_worker_credentials():
    settings = Settings(**base_values(OUTBOX_DB_PASSWORD=""))
    assert "worker.OUTBOX_DB_PASSWORD" in codes(worker_environment_checks(settings))


def test_cli_preflight_environment_succeeds_and_does_not_print_secrets(monkeypatch, capsys):
    from app.cli import preflight as preflight_cli

    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("EMAIL_VERIFICATION_HMAC_KEY", "e" * 48)
    monkeypatch.setenv("OUTBOX_DB_PASSWORD", "worker-password-with-enough-length-000000")
    assert preflight_cli.main(["--stage", "environment"]) == 0
    output = capsys.readouterr().out
    assert "SECRET_KEY=" not in output
    assert "worker-password-with-enough-length-000000" not in output
    assert "Resumo:" in output


def test_cli_preflight_commercial_skips_without_hotmart(monkeypatch, capsys):
    from app.cli import preflight as preflight_cli

    monkeypatch.setenv("HOTMART_ENABLED", "false")
    assert preflight_cli.main(["--stage", "commercial"]) == 0
    assert "[SKIP] commercial.hotmart" in capsys.readouterr().out


def test_environment_checks_requires_email_sender():
    settings = Settings(**base_values(EMAIL_FROM="sem-remetente"))
    assert "config.EMAIL_FROM" in codes(environment_checks(settings))


def test_environment_checks_accepts_development_configuration():
    settings = Settings(
        **base_values(
            ENV="development",
            DEBUG="true",
            SESSION_COOKIE_SECURE="false",
            APP_BASE_URL="http://localhost:3010",
        )
    )
    assert not failures(environment_checks(settings))


def test_production_settings_reject_missing_outbox_password():
    with pytest.raises(ValidationError):
        Settings(**production_values(OUTBOX_DB_PASSWORD=""))


def test_production_settings_reject_missing_email_verification_key():
    with pytest.raises(ValidationError):
        Settings(**production_values(EMAIL_VERIFICATION_HMAC_KEY=""))


def test_environment_checks_rejects_migration_role_equal_to_app_role():
    settings = Settings(
        **base_values(
            MIGRATION_DATABASE_URL="postgresql+psycopg://app:migration-password@localhost:5432/fortexahome_test"
        )
    )
    assert "config.migration_role" in codes(environment_checks(settings))


def test_reconciliation_enabled_requires_credentials_and_product():
    settings = Settings(
        **production_values(
            HOTMART_RECONCILIATION_ENABLED="true",
            HOTMART_RECONCILIATION_CLIENT_ID="",
            HOTMART_RECONCILIATION_CLIENT_SECRET="",
            HOTMART_RECONCILIATION_PRODUCT_ID="",
            HOTMART_PRODUCT_SLUG="",
        )
    )
    assert "config.hotmart_reconciliation" in codes(environment_checks(settings))


def test_valid_reconciliation_configuration_does_not_fail_preflight():
    settings = Settings(
        **production_values(
            HOTMART_RECONCILIATION_ENABLED="true",
            HOTMART_RECONCILIATION_CLIENT_ID="client-id",
            HOTMART_RECONCILIATION_CLIENT_SECRET="client-secret",
            HOTMART_RECONCILIATION_PRODUCT_ID="1234567",
            HOTMART_PRODUCT_SLUG="fortexahome",
        )
    )
    results = environment_checks(settings)
    assert "config.hotmart_reconciliation" not in codes(results)


def test_environment_checks_rejects_lockout_disabled_in_production():
    settings = Settings(**production_values(LOGIN_LOCKOUT_ENABLED="false"))
    assert "config.LOGIN_LOCKOUT_ENABLED" in codes(environment_checks(settings))


def test_environment_checks_rejects_sandbox_provider_in_production():
    with pytest.raises(ValidationError):
        Settings(
            **production_values(
                PAYMENT_SANDBOX_ENABLED="true",
                PAYMENT_WEBHOOK_SECRET="test-webhook-secret-not-for-production-0000",
                PAYMENT_PROVIDER="hotmart",
            )
        )


def test_environment_checks_rejects_debug_log_level_in_production():
    with pytest.raises(ValidationError):
        Settings(**production_values(LOG_LEVEL="DEBUG"))
