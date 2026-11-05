from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import database


class FakeConnection:
    def __init__(self, *, role: str, superuser: bool = False, bypassrls: bool = False):
        self.role = role
        self.superuser = superuser
        self.bypassrls = bypassrls

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, statement):
        if "pg_roles" not in str(statement):
            return SimpleNamespace()
        result = SimpleNamespace(
            current_user=self.role,
            rolsuper=self.superuser,
            rolbypassrls=self.bypassrls,
        )
        return SimpleNamespace(one=lambda: result)


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def prepare(monkeypatch, *, role: str, superuser: bool = False, bypassrls: bool = False):
    monkeypatch.setattr(database.settings, "ENV", "production")
    monkeypatch.setattr(database.settings, "APP_DB_USER", "fortexa_app")
    monkeypatch.setattr(
        database,
        "engine",
        FakeEngine(FakeConnection(role=role, superuser=superuser, bypassrls=bypassrls)),
    )


def test_production_database_accepts_configured_runtime_role(monkeypatch):
    prepare(monkeypatch, role="fortexa_app")
    database.check_database()


def test_production_database_rejects_unconfigured_role(monkeypatch):
    prepare(monkeypatch, role="other_role")
    with pytest.raises(RuntimeError, match="APP_DB_USER"):
        database.check_database()


def test_production_database_rejects_superuser(monkeypatch):
    prepare(monkeypatch, role="fortexa_app", superuser=True)
    with pytest.raises(RuntimeError, match="SUPERUSER"):
        database.check_database()


def test_production_database_rejects_bypassrls(monkeypatch):
    prepare(monkeypatch, role="fortexa_app", bypassrls=True)
    with pytest.raises(RuntimeError, match="BYPASSRLS"):
        database.check_database()
