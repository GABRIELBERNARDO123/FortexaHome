from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.core.config import Settings

Level = Literal["OK", "WARN", "FAIL", "SKIP"]


@dataclass(frozen=True)
class CheckResult:
    level: Level
    code: str
    message: str


def _result(level: Level, code: str, message: str) -> CheckResult:
    return CheckResult(level=level, code=code, message=message)


def validation_error_results(exc: ValidationError) -> list[CheckResult]:
    """Translate settings validation errors without exposing input values."""
    results: list[CheckResult] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part not in {"body", "__root__"})
        code = f"config.{location or 'settings'}"
        message = str(error.get("msg", "configuração inválida"))
        results.append(_result("FAIL", code, message))
    return results


def _parse_url(value: str, name: str) -> tuple[object | None, CheckResult | None]:
    try:
        parsed = make_url(value)
    except Exception:
        return None, _result("FAIL", f"config.{name}", f"{name} não é uma URL de conexão válida")
    if not parsed.drivername.startswith("postgresql"):
        return None, _result("FAIL", f"config.{name}", f"{name} deve usar um driver PostgreSQL")
    return parsed, None


def _secret_length(settings: Settings, name: str, minimum: int) -> CheckResult:
    value = getattr(settings, name)
    if len(value) < minimum:
        return _result(
            "FAIL",
            f"config.{name}",
            f"{name} deve ter pelo menos {minimum} caracteres",
        )
    return _result("OK", f"config.{name}", f"{name} tem tamanho suficiente")


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("troque_", "change_me", "changeme", "example_secret", "your_secret"))


def environment_checks(settings: Settings) -> list[CheckResult]:
    """Non-secret environment readiness checks. Settings remains the validation source."""
    results: list[CheckResult] = []

    if settings.ENV.lower() not in {"development", "test", "production"}:
        results.append(_result("FAIL", "config.ENV", "ENV deve ser development, test ou production"))
    else:
        results.append(_result("OK", "config.ENV", f"ENV reconhecido: {settings.ENV.lower()}"))

    results.append(_result("OK", "config.settings", "configurações estruturais aceitas pelo Settings"))
    results.append(_secret_length(settings, "SECRET_KEY", 32))
    results.append(_secret_length(settings, "PII_LOOKUP_KEY", 32))
    results.append(_secret_length(settings, "LICENSE_HMAC_KEY", 32))
    results.append(_secret_length(settings, "EMAIL_VERIFICATION_HMAC_KEY", 32))
    if settings.is_production:
        results.append(_secret_length(settings, "RATE_LIMIT_HMAC_KEY", 32))
    elif settings.RATE_LIMIT_ENABLED and not settings.RATE_LIMIT_HMAC_KEY:
        results.append(
            _result(
                "WARN",
                "config.RATE_LIMIT_HMAC_KEY",
                "RATE_LIMIT_HMAC_KEY vazia; aceitável somente em desenvolvimento/teste",
            )
        )
    else:
        results.append(_result("OK", "config.RATE_LIMIT_HMAC_KEY", "chave de rate limit configurada"))

    try:
        if len(settings.pii_encryption_bytes) != 32:
            results.append(_result("FAIL", "config.PII_ENCRYPTION_KEY", "PII_ENCRYPTION_KEY deve ter 32 bytes"))
        else:
            results.append(_result("OK", "config.PII_ENCRYPTION_KEY", "PII_ENCRYPTION_KEY tem 32 bytes"))
    except ValueError:
        results.append(_result("FAIL", "config.PII_ENCRYPTION_KEY", "PII_ENCRYPTION_KEY deve ser base64 válido"))

    app_url, app_url_error = _parse_url(settings.DATABASE_URL, "DATABASE_URL")
    migration_url, migration_error = _parse_url(settings.MIGRATION_DATABASE_URL, "MIGRATION_DATABASE_URL")
    results.extend(item for item in (app_url_error, migration_error) if item is not None)
    if app_url is not None:
        results.append(_result("OK", "config.DATABASE_URL", "DATABASE_URL usa driver PostgreSQL"))
    if migration_url is not None:
        results.append(_result("OK", "config.MIGRATION_DATABASE_URL", "MIGRATION_DATABASE_URL usa driver PostgreSQL"))

    if not settings.APP_DB_USER.strip():
        results.append(_result("FAIL", "config.APP_DB_USER", "APP_DB_USER não pode ser vazio"))
    else:
        results.append(_result("OK", "config.APP_DB_USER", "APP_DB_USER está definido"))

    if not settings.OUTBOX_DB_USER.strip():
        results.append(_result("FAIL", "config.OUTBOX_DB_USER", "OUTBOX_DB_USER não pode ser vazio"))
    elif settings.OUTBOX_DB_USER == settings.APP_DB_USER:
        results.append(
            _result("FAIL", "config.OUTBOX_DB_USER", "OUTBOX_DB_USER deve ser diferente de APP_DB_USER")
        )
    else:
        results.append(_result("OK", "config.OUTBOX_DB_USER", "OUTBOX_DB_USER é separado de APP_DB_USER"))

    if not settings.OUTBOX_DB_PASSWORD.strip():
        results.append(_result("FAIL", "config.OUTBOX_DB_PASSWORD", "OUTBOX_DB_PASSWORD não pode ser vazia"))
    elif settings.is_production and len(settings.OUTBOX_DB_PASSWORD) < 32:
        results.append(
            _result("FAIL", "config.OUTBOX_DB_PASSWORD", "OUTBOX_DB_PASSWORD deve ter pelo menos 32 caracteres")
        )
    else:
        results.append(_result("OK", "config.OUTBOX_DB_PASSWORD", "OUTBOX_DB_PASSWORD está definida"))

    if app_url is not None and app_url.password and settings.OUTBOX_DB_PASSWORD:
        if app_url.password == settings.OUTBOX_DB_PASSWORD:
            results.append(
                _result(
                    "FAIL",
                    "config.role_passwords",
                    "a senha do worker deve ser diferente da senha do papel operacional",
                )
            )
        else:
            results.append(_result("OK", "config.role_passwords", "senhas dos papéis são distintas"))

    if app_url is not None and migration_url is not None:
        if app_url.username == migration_url.username:
            results.append(
                _result(
                    "FAIL",
                    "config.migration_role",
                    "a conexão de migrations deve usar um papel diferente do papel operacional",
                )
            )
        else:
            results.append(_result("OK", "config.migration_role", "papéis operacional e de migrations distintos"))
        if app_url.password and migration_url.password and app_url.password == migration_url.password:
            results.append(
                _result(
                    "FAIL",
                    "config.migration_password",
                    "a senha de migrations deve ser diferente da senha operacional",
                )
            )
        else:
            results.append(_result("OK", "config.migration_password", "senhas de migrations e operação distintas"))

    if settings.is_production:
        purposes = {
            "SECRET_KEY": settings.SECRET_KEY,
            "PII_LOOKUP_KEY": settings.PII_LOOKUP_KEY,
            "LICENSE_HMAC_KEY": settings.LICENSE_HMAC_KEY,
            "EMAIL_VERIFICATION_HMAC_KEY": settings.EMAIL_VERIFICATION_HMAC_KEY,
            "RATE_LIMIT_HMAC_KEY": settings.RATE_LIMIT_HMAC_KEY,
        }
        if len(set(purposes.values())) == len(purposes):
            results.append(_result("OK", "config.secret_purposes", "segredos têm finalidades distintas"))
        else:
            results.append(
                _result("FAIL", "config.secret_purposes", "segredos de finalidades diferentes não podem ser iguais")
            )

        placeholders = [
            name
            for name, value in (
                ("SECRET_KEY", settings.SECRET_KEY),
                ("PII_ENCRYPTION_KEY", settings.PII_ENCRYPTION_KEY),
                ("PII_LOOKUP_KEY", settings.PII_LOOKUP_KEY),
                ("LICENSE_HMAC_KEY", settings.LICENSE_HMAC_KEY),
                ("EMAIL_VERIFICATION_HMAC_KEY", settings.EMAIL_VERIFICATION_HMAC_KEY),
                ("RATE_LIMIT_HMAC_KEY", settings.RATE_LIMIT_HMAC_KEY),
                ("OUTBOX_DB_PASSWORD", settings.OUTBOX_DB_PASSWORD),
                ("RESEND_API_KEY", settings.RESEND_API_KEY),
                ("HOTMART_WEBHOOK_HOTTOK", settings.HOTMART_WEBHOOK_HOTTOK),
            )
            if _is_placeholder(value)
        ]
        if placeholders:
            results.append(
                _result(
                    "FAIL",
                    "config.placeholders",
                    "placeholders de exemplo detectados: " + ", ".join(placeholders),
                )
            )
        else:
            results.append(_result("OK", "config.placeholders", "nenhum placeholder de exemplo detectado"))

    if settings.EMAIL_PROVIDER not in {"dev", "resend"}:
        results.append(_result("FAIL", "config.EMAIL_PROVIDER", "EMAIL_PROVIDER deve ser dev ou resend"))
    elif settings.EMAIL_PROVIDER == "resend" and not settings.RESEND_API_KEY.strip():
        results.append(_result("FAIL", "config.RESEND_API_KEY", "RESEND_API_KEY é obrigatória com EMAIL_PROVIDER=resend"))
    else:
        results.append(_result("OK", "config.EMAIL_PROVIDER", "provedor de e-mail configurado"))

    _, sender_address = parseaddr(settings.EMAIL_FROM)
    if not sender_address or "@" not in sender_address:
        results.append(_result("FAIL", "config.EMAIL_FROM", "EMAIL_FROM deve conter um remetente de e-mail"))
    else:
        results.append(_result("OK", "config.EMAIL_FROM", "EMAIL_FROM contém um remetente"))

    base_url = settings.APP_BASE_URL.strip()
    if not base_url:
        results.append(_result("FAIL", "config.APP_BASE_URL", "APP_BASE_URL não pode ser vazia"))
    else:
        from urllib.parse import urlsplit

        parsed_base = urlsplit(base_url)
        if not parsed_base.scheme or not parsed_base.netloc:
            results.append(_result("FAIL", "config.APP_BASE_URL", "APP_BASE_URL deve ser uma URL completa"))
        elif settings.is_production and parsed_base.scheme != "https":
            results.append(_result("FAIL", "config.APP_BASE_URL", "APP_BASE_URL deve usar HTTPS em produção"))
        else:
            results.append(_result("OK", "config.APP_BASE_URL", "APP_BASE_URL está configurada"))

    if not settings.cors_origins_list:
        results.append(_result("FAIL", "config.CORS_ORIGINS", "CORS_ORIGINS deve ter ao menos uma origem"))
    else:
        results.append(_result("OK", "config.CORS_ORIGINS", "CORS_ORIGINS está configurada"))

    if settings.is_production and not settings.RATE_LIMIT_ENABLED:
        results.append(_result("FAIL", "config.RATE_LIMIT_ENABLED", "RATE_LIMIT_ENABLED deve ser true em produção"))
    elif not settings.RATE_LIMIT_ENABLED:
        results.append(_result("WARN", "config.RATE_LIMIT_ENABLED", "RATE_LIMIT_ENABLED está desabilitado"))
    else:
        results.append(_result("OK", "config.RATE_LIMIT_ENABLED", "rate limit habilitado"))

    if settings.is_production and not settings.LOGIN_LOCKOUT_ENABLED:
        results.append(
            _result(
                "FAIL",
                "config.LOGIN_LOCKOUT_ENABLED",
                "LOGIN_LOCKOUT_ENABLED deve ser true em produção",
            )
        )
    elif not settings.LOGIN_LOCKOUT_ENABLED:
        results.append(
            _result("WARN", "config.LOGIN_LOCKOUT_ENABLED", "lockout progressivo está desabilitado")
        )
    else:
        results.append(
            _result(
                "OK",
                "config.LOGIN_LOCKOUT_ENABLED",
                "lockout progressivo habilitado com parâmetros tipados",
            )
        )

    if settings.is_production and settings.LOG_LEVEL.upper() == "DEBUG":
        results.append(
            _result(
                "FAIL",
                "config.LOG_LEVEL",
                "LOG_LEVEL não pode ser DEBUG em produção",
            )
        )
    else:
        results.append(_result("OK", "config.LOG_LEVEL", "nível de log compatível"))

    if settings.PAYMENT_SANDBOX_ENABLED and settings.is_production:
        results.append(
            _result(
                "FAIL",
                "config.PAYMENT_SANDBOX_ENABLED",
                "PAYMENT_SANDBOX_ENABLED deve ser false em produção",
            )
        )
    elif settings.PAYMENT_SANDBOX_ENABLED:
        results.append(
            _result(
                "OK",
                "config.PAYMENT_SANDBOX_ENABLED",
                "sandbox HMAC habilitado fora de produção",
            )
        )
    else:
        results.append(
            _result("OK", "config.PAYMENT_SANDBOX_ENABLED", "rota sandbox HMAC desabilitada")
        )

    if not settings.TRUSTED_PROXY_IPS.strip():
        results.append(
            _result(
                "WARN" if settings.is_production else "OK",
                "config.TRUSTED_PROXY_IPS",
                "TRUSTED_PROXY_IPS vazio: confirme a topologia do proxy",
            )
        )
    else:
        invalid = False
        for item in settings.trusted_proxy_ips_list:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError:
                invalid = True
                break
        if invalid:
            results.append(_result("FAIL", "config.TRUSTED_PROXY_IPS", "TRUSTED_PROXY_IPS contém entrada inválida"))
        else:
            results.append(_result("OK", "config.TRUSTED_PROXY_IPS", "TRUSTED_PROXY_IPS é válido"))

    if settings.HOTMART_ENABLED:
        if len(settings.HOTMART_WEBHOOK_HOTTOK.strip()) < 16:
            results.append(_result("FAIL", "config.HOTMART_WEBHOOK_HOTTOK", "HOTTOK ausente ou curto demais"))
        else:
            results.append(_result("OK", "config.HOTMART_WEBHOOK_HOTTOK", "HOTTOK configurado"))
        if not settings.HOTMART_PRODUCT_UCODE.strip():
            results.append(_result("FAIL", "config.HOTMART_PRODUCT_UCODE", "UCODE da Hotmart não configurado"))
        else:
            results.append(_result("OK", "config.HOTMART_PRODUCT_UCODE", "UCODE da Hotmart configurado"))
        if not settings.HOTMART_PRODUCT_SLUG.strip():
            results.append(_result("FAIL", "config.HOTMART_PRODUCT_SLUG", "slug interno da Hotmart não configurado"))
        else:
            results.append(_result("OK", "config.HOTMART_PRODUCT_SLUG", "slug interno da Hotmart configurado"))
    else:
        results.append(_result("SKIP", "config.hotmart", "Hotmart desabilitada: credenciais não exigidas"))

    if not settings.HOTMART_RECONCILIATION_ENABLED:
        results.append(
            _result(
                "SKIP",
                "config.hotmart_reconciliation",
                "reconciliação Hotmart desabilitada",
            )
        )
    else:
        missing = [
            name
            for name, value in (
                ("HOTMART_RECONCILIATION_CLIENT_ID", settings.HOTMART_RECONCILIATION_CLIENT_ID),
                ("HOTMART_RECONCILIATION_CLIENT_SECRET", settings.HOTMART_RECONCILIATION_CLIENT_SECRET),
                ("HOTMART_RECONCILIATION_PRODUCT_ID", settings.HOTMART_RECONCILIATION_PRODUCT_ID),
                ("HOTMART_PRODUCT_SLUG", settings.HOTMART_PRODUCT_SLUG),
            )
            if not value.strip()
        ]
        if missing:
            results.append(
                _result(
                    "FAIL",
                    "config.hotmart_reconciliation",
                    "reconciliação habilitada sem: " + ", ".join(missing),
                )
            )
        elif any(
            _is_placeholder(value)
            for value in (
                settings.HOTMART_RECONCILIATION_CLIENT_ID,
                settings.HOTMART_RECONCILIATION_CLIENT_SECRET,
            )
        ):
            results.append(
                _result(
                    "FAIL",
                    "config.hotmart_reconciliation",
                    "credenciais de reconciliação contêm placeholder",
                )
            )
        elif not settings.HOTMART_RECONCILIATION_PRODUCT_ID.strip().isdigit():
            results.append(
                _result(
                    "FAIL",
                    "config.hotmart_reconciliation",
                    "HOTMART_RECONCILIATION_PRODUCT_ID deve conter apenas dígitos",
                )
            )
        else:
            results.append(
                _result(
                    "OK",
                    "config.hotmart_reconciliation",
                    "reconciliação Hotmart configurada (sem chamada externa durante o preflight)",
                )
            )

    return results


def _alembic_heads() -> list[str]:
    config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not config_path.exists():
        raise RuntimeError("alembic.ini não encontrado")
    config = Config(str(config_path))
    return list(ScriptDirectory.from_config(config).get_heads())


def database_checks(settings: Settings, engine: Engine | None = None) -> list[CheckResult]:
    if engine is None:
        from app.core.database import engine as default_engine

        engine = default_engine

    results: list[CheckResult] = []
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT current_user, current_database(), r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            ).one()
            current_user, current_database, superuser, bypass_rls = row
            results.append(
                _result(
                    "OK",
                    "database.connect",
                    f"conexão estabelecida com o banco {current_database}",
                )
            )

            if settings.is_production and current_user != settings.APP_DB_USER:
                results.append(
                    _result(
                        "FAIL",
                        "database.role",
                        f"o papel conectado deve ser {settings.APP_DB_USER}",
                    )
                )
            else:
                results.append(_result("OK", "database.role", f"papel conectado: {current_user}"))

            if superuser or bypass_rls:
                level: Level = "FAIL" if settings.is_production else "WARN"
                results.append(
                    _result(
                        level,
                        "database.role_flags",
                        "o papel não deve ter SUPERUSER nem BYPASSRLS",
                    )
                )
            else:
                results.append(_result("OK", "database.role_flags", "papel sem SUPERUSER e sem BYPASSRLS"))

            try:
                current_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            except Exception:
                current_revision = None
            if not current_revision:
                results.append(_result("FAIL", "database.alembic", "migrations ainda não foram aplicadas"))
            else:
                try:
                    heads = _alembic_heads()
                except Exception:
                    heads = []
                if len(heads) != 1:
                    results.append(
                        _result("WARN", "database.alembic", "não foi possível confirmar um head Alembic único")
                    )
                elif current_revision != heads[0]:
                    results.append(
                        _result(
                            "FAIL",
                            "database.alembic",
                            f"revisão atual {current_revision} difere do head {heads[0]}",
                        )
                    )
                else:
                    results.append(_result("OK", "database.alembic", f"migração no head {current_revision}"))

            required_privileges = [
                ("products", "SELECT"),
                ("products", "INSERT"),
                ("products", "UPDATE"),
                ("licenses", "SELECT"),
                ("licenses", "INSERT"),
                ("licenses", "UPDATE"),
                ("orders", "SELECT"),
                ("payment_events", "INSERT"),
                ("categories", "SELECT"),
                ("users", "SELECT"),
                ("sessions", "SELECT"),
                ("email_outbox", "INSERT"),
                ("rate_limit_buckets", "SELECT"),
                ("rate_limit_buckets", "INSERT"),
                ("rate_limit_buckets", "UPDATE"),
                ("rate_limit_buckets", "DELETE"),
                ("hotmart_reconciliation_observations", "SELECT"),
                ("hotmart_reconciliation_observations", "INSERT"),
                ("login_lockout_states", "SELECT"),
                ("login_lockout_states", "INSERT"),
                ("login_lockout_states", "UPDATE"),
                ("login_lockout_states", "DELETE"),
            ]
            missing: list[str] = []
            for table, privilege in required_privileges:
                allowed = connection.scalar(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": current_user, "table": table, "privilege": privilege},
                )
                if not allowed:
                    missing.append(f"{table}.{privilege}")
            column_allowed = connection.scalar(
                text("SELECT has_column_privilege(:role, 'email_outbox', 'status', 'UPDATE')"),
                {"role": current_user},
            )
            if not column_allowed:
                missing.append("email_outbox.status.UPDATE")
            if missing:
                results.append(
                    _result(
                        "FAIL",
                        "database.privileges",
                        "permissões ausentes: " + ", ".join(sorted(missing)),
                    )
                )
            else:
                results.append(_result("OK", "database.privileges", "permissões operacionais presentes"))

            reconciliation_table = connection.scalar(
                text("SELECT to_regclass('public.hotmart_reconciliation_observations')")
            )
            if reconciliation_table is None:
                results.append(
                    _result(
                        "FAIL",
                        "database.hotmart_reconciliation",
                        "tabela de observações da reconciliação ausente",
                    )
                )
            else:
                app_can_mutate = connection.scalar(
                    text(
                        "SELECT has_table_privilege(:role, 'hotmart_reconciliation_observations', 'UPDATE') "
                        "OR has_table_privilege(:role, 'hotmart_reconciliation_observations', 'DELETE')"
                    ),
                    {"role": current_user},
                )
                worker_can_read = connection.scalar(
                    text("SELECT has_table_privilege(:role, 'hotmart_reconciliation_observations', 'SELECT')"),
                    {"role": settings.OUTBOX_DB_USER},
                )
                if app_can_mutate:
                    results.append(
                        _result(
                            "FAIL",
                            "database.hotmart_reconciliation",
                            "papel operacional não deve alterar observações de reconciliação",
                        )
                    )
                elif worker_can_read:
                    results.append(
                        _result(
                            "FAIL",
                            "database.hotmart_reconciliation",
                            "worker da outbox não deve acessar observações de reconciliação",
                        )
                    )
                else:
                    results.append(
                        _result(
                            "OK",
                            "database.hotmart_reconciliation",
                            "observações de reconciliação são append-only e restritas",
                        )
                    )

            lockout_table = connection.scalar(
                text("SELECT to_regclass('public.login_lockout_states')")
            )
            if lockout_table is None:
                results.append(
                    _result("FAIL", "database.login_lockout", "tabela de lockout de login ausente")
                )
            else:
                worker_lockout_access = connection.scalar(
                    text("SELECT has_table_privilege(:role, 'login_lockout_states', 'SELECT')"),
                    {"role": settings.OUTBOX_DB_USER},
                )
                if worker_lockout_access:
                    results.append(
                        _result(
                            "FAIL",
                            "database.login_lockout",
                            "worker da outbox não deve acessar o estado de lockout",
                        )
                    )
                else:
                    results.append(
                        _result(
                            "OK",
                            "database.login_lockout",
                            "tabela de lockout presente e isolada do worker",
                        )
                    )

            product_rls = connection.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'products' AND relnamespace = 'public'::regnamespace"
                )
            ).one_or_none()
            if product_rls is None or not all(product_rls):
                results.append(_result("FAIL", "database.rls", "RLS/FORCE RLS não confirmada em products"))
            else:
                policy = connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_policies "
                        "WHERE schemaname = 'public' AND tablename = 'products' "
                        "AND policyname = 'products_catalog_write')"
                    )
                )
                if not policy:
                    results.append(
                        _result("FAIL", "database.rls", "policy products_catalog_write não encontrada")
                    )
                else:
                    results.append(_result("OK", "database.rls", "RLS e policy de catálogo confirmadas"))
    except Exception:
        results.append(_result("FAIL", "database.connect", "não foi possível validar o banco operacional (conexão ou inspeção)"))
    return results


def commercial_checks(settings: Settings, db: Session) -> list[CheckResult]:
    if not settings.HOTMART_ENABLED and not settings.HOTMART_RECONCILIATION_ENABLED:
        return [_result("SKIP", "commercial.hotmart", "Hotmart/reconciliação desabilitadas: catálogo comercial não exigido")]
    if not settings.HOTMART_PRODUCT_SLUG.strip():
        return [_result("FAIL", "commercial.slug", "HOTMART_PRODUCT_SLUG não configurado")]

    from app.services.license_service import get_product_by_slug

    try:
        product = get_product_by_slug(db, settings.HOTMART_PRODUCT_SLUG)
    except Exception:
        return [_result("FAIL", "commercial.product", "não foi possível consultar o catálogo interno")]
    if product is None:
        return [
            _result(
                "FAIL",
                "commercial.product",
                "produto interno não encontrado para o slug configurado",
            )
        ]
    if not product.active:
        return [
            _result(
                "FAIL",
                "commercial.product",
                "produto interno encontrado, mas está inativo",
            )
        ]
    return [
        _result(
            "OK",
            "commercial.product",
            "produto interno existe, está ativo e corresponde ao slug da Hotmart",
        )
    ]


def failures(results: list[CheckResult]) -> list[CheckResult]:
    return [item for item in results if item.level == "FAIL"]


def assert_environment_ready(settings: Settings, *, fail_in_any_environment: bool = False) -> list[CheckResult]:
    results = environment_checks(settings)
    problems = failures(results)
    if problems and (settings.is_production or fail_in_any_environment):
        raise RuntimeError("; ".join(item.message for item in problems))
    return results


def worker_environment_checks(settings: Settings) -> list[CheckResult]:
    results: list[CheckResult] = []
    if not settings.OUTBOX_DB_USER.strip():
        results.append(_result("FAIL", "worker.OUTBOX_DB_USER", "OUTBOX_DB_USER não pode ser vazio"))
    elif settings.OUTBOX_DB_USER == settings.APP_DB_USER:
        results.append(_result("FAIL", "worker.OUTBOX_DB_USER", "OUTBOX_DB_USER deve ser diferente de APP_DB_USER"))
    else:
        results.append(_result("OK", "worker.OUTBOX_DB_USER", "papel do worker definido"))
    if not settings.OUTBOX_DB_PASSWORD.strip():
        results.append(_result("FAIL", "worker.OUTBOX_DB_PASSWORD", "OUTBOX_DB_PASSWORD não pode ser vazia"))
    else:
        results.append(_result("OK", "worker.OUTBOX_DB_PASSWORD", "senha do worker definida"))
    if settings.EMAIL_PROVIDER == "resend" and not settings.RESEND_API_KEY.strip():
        results.append(_result("FAIL", "worker.RESEND_API_KEY", "RESEND_API_KEY é obrigatória com EMAIL_PROVIDER=resend"))
    else:
        results.append(_result("OK", "worker.EMAIL_PROVIDER", "provedor de e-mail do worker configurado"))
    return results


def assert_worker_environment_ready(settings: Settings) -> None:
    problems = failures(worker_environment_checks(settings))
    if problems:
        raise RuntimeError("; ".join(item.message for item in problems))
