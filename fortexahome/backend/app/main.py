from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import check_database
from app.core.log_safety import (
    configure_logging,
    get_request_id,
    new_request_id,
    reset_request_id,
    set_request_id,
    valid_request_id,
)
from app.core.preflight import assert_environment_ready

settings = get_settings()
configure_logging("api")
logger = logging.getLogger("fortexahome")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        issues = assert_environment_ready(settings)
        for item in issues:
            if item.level in {"WARN", "FAIL"}:
                logger.warning("Preflight %s %s: %s", item.level, item.code, item.message)
    except RuntimeError:
        logger.exception("Preflight de ambiente reprovado durante a inicialização")
        raise
    try:
        check_database()
        logger.info("Conexão com o banco de dados validada")
    except Exception:
        if settings.is_production:
            logger.exception("Banco de dados indisponível durante a inicialização")
            raise
        logger.exception("Banco de dados indisponível durante a inicialização local")
    yield


app = FastAPI(
    title="FortexaHome API",
    description="Gestão financeira doméstica FortexaHome.",
    version=__version__,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", get_request_id())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        errors.append({"field": location, "message": error.get("msg", "Valor inválido")})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Dados inválidos",
            "errors": errors,
            "request_id": _request_id(request),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    token = set_request_id(request_id)
    try:
        logger.error(
            "Erro não tratado method=%s path=%s error_type=%s",
            request.method,
            request.url.path,
            type(exc).__name__,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Erro interno. Tente novamente em instantes.",
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )
    finally:
        reset_request_id(token)


def _same_origin(request: Request, origin: str) -> bool:
    parsed = urlsplit(origin)
    if not parsed.scheme or not parsed.netloc:
        return False
    expected = {
        f"{urlsplit(item).scheme}://{urlsplit(item).netloc}".lower()
        for item in settings.cors_origins_list
    }
    expected.add(f"{urlsplit(settings.APP_BASE_URL).scheme}://{urlsplit(settings.APP_BASE_URL).netloc}".lower())
    return f"{parsed.scheme}://{parsed.netloc}".lower() in expected


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = valid_request_id(request.headers.get("x-request-id")) or new_request_id()
    request.state.request_id = request_id
    token = set_request_id(request_id)
    started = time.perf_counter()
    try:
        if request.url.path.startswith(f"{settings.API_V1_PREFIX}/webhooks/"):
            pass
        elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            fetch_site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            if fetch_site == "cross-site":
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Requisição de origem não permitida"},
                )
                response.headers["X-Request-ID"] = request_id
                return response
            if origin and not _same_origin(request, origin):
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Origem não autorizada"},
                )
                response.headers["X-Request-ID"] = request_id
                return response

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        if not (request.url.path.startswith("/docs") or request.url.path.startswith("/redoc")):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        logger.info(
            "%s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response
    finally:
        reset_request_id(token)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With", "X-Request-ID", "Idempotency-Key"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
    max_age=600,
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"app": "FortexaHome", "version": __version__, "api": settings.API_V1_PREFIX}
