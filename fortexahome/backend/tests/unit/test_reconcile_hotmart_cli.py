from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.cli import reconcile_hotmart as cli
from app.services.hotmart_reconciliation_service import ReconciliationRun


def settings(**overrides):
    values = {
        "HOTMART_RECONCILIATION_ENABLED": True,
        "HOTMART_RECONCILIATION_CLIENT_ID": "client-id",
        "HOTMART_RECONCILIATION_CLIENT_SECRET": "client-secret",
        "HOTMART_RECONCILIATION_PRODUCT_ID": "1234567",
        "HOTMART_RECONCILIATION_ENVIRONMENT": "sandbox",
        "HOTMART_RECONCILIATION_TIMEOUT_SECONDS": 10.0,
        "HOTMART_RECONCILIATION_MAX_ATTEMPTS": 3,
        "HOTMART_RECONCILIATION_BACKOFF_BASE_SECONDS": 1.0,
        "HOTMART_RECONCILIATION_MAX_TRANSACTIONS": 25,
        "HOTMART_RECONCILIATION_LOOKBACK_HOURS": 72,
        "HOTMART_RECONCILIATION_REQUEST_INTERVAL_SECONDS": 0.0,
        "HOTMART_PRODUCT_SLUG": "fortexahome",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def install_fakes(monkeypatch, *, enabled=True, captured=None):
    monkeypatch.setattr(cli, "get_settings", lambda: settings(HOTMART_RECONCILIATION_ENABLED=enabled))

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def fake_run(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return ReconciliationRun(run_id=uuid.uuid4(), results=[], stopped_early=False)

    monkeypatch.setattr(cli, "HotmartApiClient", FakeClient)
    monkeypatch.setattr(cli, "run_reconciliation", fake_run)


def test_cli_refuses_when_reconciliation_is_disabled(monkeypatch, capsys):
    install_fakes(monkeypatch, enabled=False)
    assert cli.main(["--transaction", "TX-1"]) == 2
    assert "desabilitada" in capsys.readouterr().out


def test_cli_requires_credentials(monkeypatch, capsys):
    install_fakes(monkeypatch)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: settings(HOTMART_RECONCILIATION_CLIENT_SECRET=""),
    )
    assert cli.main(["--transaction", "TX-1"]) == 2
    assert "HOTMART_RECONCILIATION_CLIENT_SECRET" in capsys.readouterr().out


def test_cli_defaults_to_dry_run_and_uses_configured_interval(monkeypatch, capsys):
    captured: dict = {}
    install_fakes(monkeypatch, captured=captured)
    assert cli.main(["--transaction", "TX-1"]) == 0
    assert captured["dry_run"] is True
    assert captured["transaction"] == "TX-1"
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "Nenhum estado comercial foi alterado" in out


def test_cli_apply_is_explicit(monkeypatch, capsys):
    captured: dict = {}
    install_fakes(monkeypatch, captured=captured)
    assert cli.main(["--transaction", "TX-1", "--apply"]) == 0
    assert captured["dry_run"] is False
    assert "APLICAÇÃO" in capsys.readouterr().out


def test_cli_rejects_limit_above_configured_maximum(monkeypatch, capsys):
    install_fakes(monkeypatch)
    assert cli.main(["--limit", "26"]) == 2
    assert "HOTMART_RECONCILIATION_MAX_TRANSACTIONS" in capsys.readouterr().out


def test_cli_json_output_is_machine_readable(monkeypatch, capsys):
    install_fakes(monkeypatch)
    assert cli.main(["--transaction", "TX-1", "--json"]) == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["transactions"] == 0
