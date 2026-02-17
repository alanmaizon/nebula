from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import get_conn


router = APIRouter()

_READY_CACHE_TTL_SECONDS = 30.0
_ready_cache: dict[str, object] = {
    "ts": 0.0,
    "ok": None,
    "payload": None,
}


def _database_backend_label(database_url: str) -> str:
    url = (database_url or "").strip().lower()
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgres"
    if url.startswith("sqlite:///"):
        return "sqlite"
    return "unknown"


def _normalize_storage_backend(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"", "local", "filesystem", "fs"}:
        return "local"
    if normalized in {"s3"}:
        return "s3"
    return "unknown"


def _cache_set(ok: bool, payload: dict[str, object]) -> None:
    _ready_cache["ts"] = time.time()
    _ready_cache["ok"] = ok
    _ready_cache["payload"] = payload


def _cache_get() -> dict[str, object] | None:
    now = time.time()
    ts = float(_ready_cache.get("ts") or 0.0)
    if now - ts > _READY_CACHE_TTL_SECONDS:
        return None
    payload = _ready_cache.get("payload")
    if isinstance(payload, dict):
        return payload
    return None


@router.get("/")
def root() -> dict[str, str]:
    return {"service": "nebula-backend", "status": "running"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@router.get("/ready", response_model=None)
def ready() -> JSONResponse:
    cached = _cache_get()
    if cached is not None:
        ok = bool(_ready_cache.get("ok"))
        return JSONResponse(status_code=200 if ok else 503, content=cached)

    payload: dict[str, object] = {
        "status": "ready",
        "environment": settings.app_env,
        "checks": {},
    }

    # DB connectivity check
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        payload["checks"]["db"] = {
            "ok": True,
            "backend": _database_backend_label(settings.database_url),
        }
    except Exception as exc:
        payload["status"] = "not_ready"
        payload["checks"]["db"] = {
            "ok": False,
            "backend": _database_backend_label(settings.database_url),
            "error": str(exc),
        }
        _cache_set(False, payload)
        return JSONResponse(status_code=503, content=payload)

    # Storage check (local or S3)
    storage_backend = _normalize_storage_backend(settings.storage_backend)
    if storage_backend == "local":
        try:
            root = Path(settings.storage_root)
            root.mkdir(parents=True, exist_ok=True)
            token = f"{time.time()}-{uuid4()}"
            probe = root / ".ready_probe"
            probe.write_text(token, encoding="utf-8")
            read_back = probe.read_text(encoding="utf-8")
            probe.unlink(missing_ok=True)
            if read_back != token:
                raise RuntimeError("local storage probe mismatch")
            payload["checks"]["storage"] = {"ok": True, "backend": "local"}
        except Exception as exc:
            payload["status"] = "not_ready"
            payload["checks"]["storage"] = {"ok": False, "backend": "local", "error": str(exc)}
            _cache_set(False, payload)
            return JSONResponse(status_code=503, content=payload)
    elif storage_backend == "s3":
        bucket = str(settings.s3_bucket or "").strip()
        prefix = str(settings.s3_prefix or "").strip().strip("/")
        base = f"{prefix}/" if prefix else ""
        key = f"{base}readyz/{settings.app_env}/backend.txt"
        token = f"{time.time()}-{uuid4()}"
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            payload["status"] = "not_ready"
            payload["checks"]["storage"] = {"ok": False, "backend": "s3", "error": str(exc)}
            _cache_set(False, payload)
            return JSONResponse(status_code=503, content=payload)

        try:
            client = boto3.client("s3", region_name=settings.aws_region)
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=token.encode("utf-8"),
                ContentType="text/plain",
            )
            response = client.get_object(Bucket=bucket, Key=key)
            body = response.get("Body")
            if body is None:
                raise RuntimeError("S3 get_object returned no Body")
            read_back = body.read().decode("utf-8", errors="replace")
            if read_back != token:
                raise RuntimeError("S3 readiness probe mismatch")
            payload["checks"]["storage"] = {"ok": True, "backend": "s3", "bucket": bucket, "key": key}
        except Exception as exc:  # pragma: no cover - depends on AWS runtime integration
            payload["status"] = "not_ready"
            payload["checks"]["storage"] = {"ok": False, "backend": "s3", "bucket": bucket, "key": key, "error": str(exc)}
            _cache_set(False, payload)
            return JSONResponse(status_code=503, content=payload)
    else:
        payload["status"] = "not_ready"
        payload["checks"]["storage"] = {"ok": False, "backend": storage_backend, "error": "unsupported storage backend"}
        _cache_set(False, payload)
        return JSONResponse(status_code=503, content=payload)

    _cache_set(True, payload)
    return JSONResponse(status_code=200, content=payload)
