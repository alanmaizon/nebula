from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from app.config import Settings

logger = logging.getLogger("nebula.storage")


class StorageError(RuntimeError):
    """Raised when document storage read/write fails."""


def _normalize_backend(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"local", "filesystem", "fs"}:
        return "local"
    if normalized in {"s3"}:
        return "s3"
    raise StorageError(f"Unsupported STORAGE_BACKEND '{value}'. Use 'local' or 's3'.")


def _is_s3_uri(path: str) -> bool:
    return path.strip().lower().startswith("s3://")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    raw = uri.strip()
    if not _is_s3_uri(raw):
        raise StorageError(f"Not an S3 URI: '{uri}'")
    # s3://bucket/key...
    without_scheme = raw[5:]
    parts = without_scheme.split("/", 1)
    bucket = parts[0].strip()
    key = parts[1].strip() if len(parts) > 1 else ""
    if not bucket or not key:
        raise StorageError(f"Invalid S3 URI: '{uri}' (expected s3://<bucket>/<key>)")
    return bucket, key


def save_document_bytes(
    *,
    settings: Settings,
    project_id: str,
    upload_batch_id: str,
    file_name: str,
    content_type: str,
    content: bytes,
) -> str:
    backend = _normalize_backend(settings.storage_backend)

    safe_name = Path(file_name).name or "upload.bin"
    object_suffix = f"{uuid4()}_{safe_name}"

    if backend == "local":
        project_folder = Path(settings.storage_root) / project_id
        project_folder.mkdir(parents=True, exist_ok=True)
        destination = project_folder / object_suffix
        destination.write_bytes(content)
        return str(destination)

    bucket = str(settings.s3_bucket or "").strip()
    if not bucket:
        raise StorageError("S3 storage backend selected but S3_BUCKET is not configured.")
    prefix = str(settings.s3_prefix or "").strip().strip("/")
    base = f"{prefix}/" if prefix else ""
    key = f"{base}uploads/{project_id}/{upload_batch_id}/{object_suffix}"

    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise StorageError("boto3 is required for S3 storage backend.") from exc

    client = boto3.client("s3", region_name=settings.aws_region)
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=content_type or "application/octet-stream",
        )
    except Exception as exc:  # pragma: no cover - depends on AWS runtime integration
        raise StorageError(f"Failed to write document to S3 (bucket={bucket}, key={key}): {exc}") from exc

    return f"s3://{bucket}/{key}"


def load_document_bytes(*, settings: Settings, storage_path: str) -> bytes:
    raw = str(storage_path or "").strip()
    if not raw:
        raise StorageError("Missing storage path.")

    if _is_s3_uri(raw):
        bucket, key = _parse_s3_uri(raw)
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise StorageError("boto3 is required for S3 storage backend.") from exc

        client = boto3.client("s3", region_name=settings.aws_region)
        try:
            response = client.get_object(Bucket=bucket, Key=key)
            body = response.get("Body")
            if body is None:
                raise StorageError(f"S3 get_object returned no body (bucket={bucket}, key={key}).")
            return body.read()
        except StorageError:
            raise
        except Exception as exc:  # pragma: no cover - depends on AWS runtime integration
            raise StorageError(f"Failed to read document from S3 (bucket={bucket}, key={key}): {exc}") from exc

    path = Path(raw)
    if not path.exists():
        raise StorageError(f"Stored file not found at '{raw}'.")
    return path.read_bytes()

