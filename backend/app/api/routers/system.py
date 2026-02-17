from fastapi import APIRouter

from app.config import settings


router = APIRouter()


@router.get("/")
def root() -> dict[str, str]:
    return {"service": "nebula-backend", "status": "running"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@router.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}
