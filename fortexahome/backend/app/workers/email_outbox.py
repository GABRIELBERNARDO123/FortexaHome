from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.log_safety import configure_logging
from app.core.preflight import assert_worker_environment_ready
from app.services.email_outbox_service import requeue_dead, run_batch

settings = get_settings()
logger = logging.getLogger("fortexahome.outbox_worker")
_HEARTBEAT = Path("/tmp/fortexahome-outbox-worker-heartbeat")


def make_worker_session_factory():
    worker_url = make_url(settings.DATABASE_URL).set(
        username=settings.OUTBOX_DB_USER,
        password=settings.OUTBOX_DB_PASSWORD,
    )
    worker_engine = create_engine(worker_url, pool_pre_ping=True, pool_size=2, max_overflow=2)
    return worker_engine, sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False, future=True)


def check_worker(factory) -> None:
    with factory() as db:
        user, superuser, bypass = db.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
        if user != settings.OUTBOX_DB_USER or superuser or bypass:
            raise RuntimeError("A identidade do worker deve ser OUTBOX_DB_USER sem SUPERUSER/BYPASSRLS")
        db.execute(text("SELECT id FROM email_outbox LIMIT 0"))


def check_heartbeat() -> None:
    try:
        last_beat = float(_HEARTBEAT.read_text(encoding="ascii"))
    except (OSError, ValueError):
        raise RuntimeError("O worker da outbox ainda não registrou heartbeat") from None
    if time.time() - last_beat > max(180, settings.OUTBOX_POLL_SECONDS * 5):
        raise RuntimeError("O loop do worker da outbox está sem heartbeat")


def write_heartbeat() -> None:
    _HEARTBEAT.write_text(str(time.time()), encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Processa a outbox transacional de e-mails")
    parser.add_argument("--check", action="store_true", help="valida a conexão/identidade sem iniciar o loop")
    parser.add_argument("--requeue-dead", help="re-enfileira pelo UUID um evento dead ainda válido")
    args = parser.parse_args()
    configure_logging("outbox_worker")
    try:
        assert_worker_environment_ready(settings)
    except RuntimeError as exc:
        logger.error("Preflight do worker reprovado error_type=%s", type(exc).__name__)
        raise SystemExit(1) from None
    worker_engine, factory = make_worker_session_factory()
    try:
        check_worker(factory)
        if args.check:
            check_heartbeat()
            return
        if args.requeue_dead:
            try:
                event_id = uuid.UUID(args.requeue_dead)
            except ValueError:
                raise SystemExit("UUID de evento inválido") from None
            with factory() as db:
                requeued = requeue_dead(db, event_id)
            if not requeued:
                raise SystemExit("Evento dead indisponível, expirado ou sem payload recuperável")
            logger.info("Evento dead re-enfileirado id=%s", event_id)
            return
        stopping = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stopping.set())
        signal.signal(signal.SIGINT, lambda *_: stopping.set())
        worker_id = uuid.uuid4()
        logger.info("Worker da outbox iniciado")
        last_status_log = 0.0
        while not stopping.is_set():
            write_heartbeat()
            counts = run_batch(factory, worker_id)
            now = time.monotonic()
            if now - last_status_log >= settings.OUTBOX_STATUS_LOG_SECONDS:
                from app.services.email_outbox_service import queue_snapshot
                with factory() as db:
                    snapshot = queue_snapshot(db)
                logger.info(
                    "Estado da outbox: pending=%s processing=%s expired_leases=%s dead=%s "
                    "oldest_pending_seconds=%s provider_errors_15m=%s",
                    snapshot["pending"], snapshot["processing"], snapshot["expired_leases"],
                    snapshot["dead"], snapshot["oldest_pending_seconds"], snapshot["provider_errors_15m"],
                )
                last_status_log = now
            if counts["claimed"]:
                logger.info(
                    "Lote da outbox processado: claimed=%d sent=%d pending=%d dead=%d cancelled=%d",
                    counts["claimed"], counts["sent"], counts["pending"], counts["dead"], counts["cancelled"],
                )
            stopping.wait(settings.OUTBOX_POLL_SECONDS)
        logger.info("Worker da outbox encerrado")
    finally:
        worker_engine.dispose()


if __name__ == "__main__":
    main()
