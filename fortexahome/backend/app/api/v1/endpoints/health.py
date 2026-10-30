from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.core.database import engine

router = APIRouter(tags=["saúde"])


@router.get("/health")
def health() -> JSONResponse:
    database_status = "up"
    status_code = 200
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database_status = "down"
        status_code = 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if status_code == 200 else "degraded",
            "app": "FortexaHome",
            "version": __version__,
            "database": database_status,
            "time": datetime.now(timezone.utc).isoformat(),
        },
    )
