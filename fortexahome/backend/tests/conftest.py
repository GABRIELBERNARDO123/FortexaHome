from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


_TEST_SECRET_ENV = {
    "ENV": "test",
    "DEBUG": "true",
    "DATABASE_URL": "postgresql+psycopg://test_runtime:test_runtime_local_only@localhost:5432/fortexahome_test",
    "MIGRATION_DATABASE_URL": "postgresql+psycopg://test_migrator:test_migrator_local_only@localhost:5432/fortexahome_test",
    "APP_DB_USER": "test_runtime",
    "OUTBOX_DB_USER": "test_outbox_worker",
    "OUTBOX_DB_PASSWORD": "test_outbox_worker_local_only_password",
    "TEST_POSTGRES_DB": "fortexahome_test",
    "SECRET_KEY": "test-secret-key-not-for-production-000000000",
    "PII_ENCRYPTION_KEY": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
    "PII_LOOKUP_KEY": "test-pii-lookup-key-not-for-production-000000",
    "LICENSE_HMAC_KEY": "test-license-hmac-key-not-for-production-0000",
    "CORS_ORIGINS": "http://localhost:3010",
    "PAYMENT_WEBHOOK_SECRET": "test-webhook-secret-not-for-production",
    "PAYMENT_SANDBOX_ENABLED": "true",
    "EMAIL_VERIFICATION_HMAC_KEY": "test-email-verification-hmac-key-0000000000",
    "RATE_LIMIT_HMAC_KEY": "test-rate-limit-hmac-key-not-for-production-0000",
}
for _name, _value in _TEST_SECRET_ENV.items():
    os.environ.setdefault(_name, _value)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-integration", action="store_true", help="run tests requiring isolated PostgreSQL")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return
    marker = pytest.mark.skip(reason="pass --run-integration to enable PostgreSQL tests")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(marker)


@pytest.fixture(scope="session")
def integration_database() -> Iterator[None]:
    """Validate both connections before migrations or test writes are allowed."""
    import os
    from urllib.parse import urlsplit

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    expected = os.environ.get("TEST_POSTGRES_DB", "fortexahome_test")
    if expected != "fortexahome_test":
        raise RuntimeError("TEST_POSTGRES_DB deve ser exatamente fortexahome_test")
    runtime_url = os.environ.get("TEST_DATABASE_URL", "")
    migration_url = os.environ.get("TEST_MIGRATION_DATABASE_URL", "")
    if not runtime_url or not migration_url:
        raise RuntimeError("Defina TEST_DATABASE_URL e TEST_MIGRATION_DATABASE_URL para a suíte PostgreSQL")
    parsed_runtime, parsed_migration = urlsplit(runtime_url), urlsplit(migration_url)
    if parsed_runtime.path.lstrip("/") != expected or parsed_migration.path.lstrip("/") != expected:
        raise RuntimeError("As URLs de teste devem apontar somente para fortexahome_test")
    if parsed_runtime.hostname not in {"test-db", "localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("O host PostgreSQL de teste deve ser local ou o serviço isolado test-db")
    if parsed_runtime.hostname != parsed_migration.hostname:
        raise RuntimeError("As conexões operacional e de migration devem usar o mesmo servidor de teste")
    if parsed_runtime.username == parsed_migration.username:
        raise RuntimeError("O papel de migrations deve ser separado do papel operacional")
    if os.environ.get("DATABASE_URL") != runtime_url or os.environ.get("MIGRATION_DATABASE_URL") != migration_url:
        raise RuntimeError("URLs ativas da aplicação devem ser exatamente as URLs de teste validadas")

    runtime_engine = create_engine(runtime_url)
    migration_engine = create_engine(migration_url)
    try:
        with runtime_engine.connect() as connection:
            db_name, is_superuser, bypass_rls = connection.execute(
                text("SELECT current_database(), rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()
            if db_name != expected:
                raise RuntimeError("A conexão operacional não está no banco de testes esperado")
            if is_superuser or bypass_rls:
                raise RuntimeError("A conexão operacional deve usar um usuário sem SUPERUSER e BYPASSRLS")
        with migration_engine.connect() as connection:
            db_name = connection.scalar(text("SELECT current_database()"))
            if db_name != expected:
                raise RuntimeError("A conexão de migrations não está no banco de testes esperado")

        config = Config("alembic.ini")
        command.upgrade(config, "head")
        yield
    finally:
        runtime_engine.dispose()
        migration_engine.dispose()
