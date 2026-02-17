from contextlib import asynccontextmanager
from functools import lru_cache
import logging
from pathlib import Path
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.pipeline import build_pipeline_router
from app.api.routers.projects import build_projects_router
from app.api.routers.system import router as system_router
from app.config import settings
from app.db import init_db
from app.nova_runtime import BedrockNovaOrchestrator, validate_bedrock_model_ids
from app.observability import (
    configure_logging,
    normalize_request_id,
    reset_request_id,
    sanitize_for_logging,
    set_request_id,
)
from app.retrieval import EmbeddingService
from app.version import APP_VERSION

logger = logging.getLogger("nebula.api")


@lru_cache(maxsize=1)
def _cached_nova_orchestrator() -> BedrockNovaOrchestrator:
    return BedrockNovaOrchestrator(settings=settings)


def get_nova_orchestrator() -> BedrockNovaOrchestrator:
    return _cached_nova_orchestrator()


@lru_cache(maxsize=1)
def _cached_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        mode=settings.embedding_mode,
        aws_region=settings.aws_region,
        bedrock_model_id=settings.bedrock_embedding_model_id,
    )


def get_embedding_service() -> EmbeddingService:
    return _cached_embedding_service()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    logger.info("application_startup", extra={"event": "application_startup", "environment": settings.app_env})
    if settings.bedrock_validate_model_ids_on_startup:
        validate_bedrock_model_ids(settings)
    init_db()
    if str(settings.storage_backend or "").strip().lower() in {"", "local", "filesystem", "fs"}:
        Path(settings.storage_root).mkdir(parents=True, exist_ok=True)
    yield
    logger.info("application_shutdown", extra={"event": "application_shutdown"})


def create_app() -> FastAPI:
    cors_origins = settings.cors_origins_list
    if settings.cors_allow_credentials and any(origin == "*" for origin in cors_origins):
        raise RuntimeError("Invalid CORS_ORIGINS: wildcard '*' is not allowed when credentials are enabled.")
    if settings.app_env == "production":
        insecure = [origin for origin in cors_origins if origin.strip().lower().startswith("http://")]
        if insecure:
            raise RuntimeError(
                "Invalid CORS_ORIGINS for production: use https:// origins (or empty to disable CORS). "
                f"Found: {insecure}"
            )
        local = [
            origin
            for origin in cors_origins
            if ("localhost" in origin.lower() or "127.0.0.1" in origin.lower())
        ]
        if local:
            raise RuntimeError(
                "Invalid CORS_ORIGINS for production: localhost origins are not allowed. "
                f"Found: {local}"
            )

    app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", settings.request_id_header],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = normalize_request_id(request.headers.get(settings.request_id_header))
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()

        logger.info(
            "request_started",
            extra={
                "event": "request_started",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": sanitize_for_logging(dict(request.query_params)),
                "client_ip": request.client.host if request.client else None,
            },
        )

        try:
            response = await call_next(request)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers[settings.request_id_header] = request_id
            logger.info(
                "request_completed",
                extra={
                    "event": "request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": elapsed_ms,
                },
            )
            return response
        except Exception:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": elapsed_ms,
                },
            )
            raise
        finally:
            reset_request_id(token)

    projects_router = build_projects_router(get_embedding_service=lambda: get_embedding_service())
    pipeline_router = build_pipeline_router(
        get_nova_orchestrator=lambda: get_nova_orchestrator(),
        get_embedding_service=lambda: get_embedding_service(),
    )
    api_projects_router = build_projects_router(get_embedding_service=lambda: get_embedding_service())
    api_pipeline_router = build_pipeline_router(
        get_nova_orchestrator=lambda: get_nova_orchestrator(),
        get_embedding_service=lambda: get_embedding_service(),
    )

    app.include_router(system_router)
    app.include_router(projects_router)
    app.include_router(pipeline_router)
    # Keep root routes for compatibility and expose /api/* aliases for same-origin frontend routing.
    app.include_router(api_projects_router, prefix="/api")
    app.include_router(api_pipeline_router, prefix="/api")

    return app


app = create_app()
