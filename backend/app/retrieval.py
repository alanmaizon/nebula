from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
}

logger = logging.getLogger("nebula.retrieval")

EmbeddingMode = Literal["hash", "bedrock", "hybrid"]


@dataclass(frozen=True)
class ExtractedPage:
    page: int
    text: str


@dataclass(frozen=True)
class ChunkPayload:
    chunk_index: int
    page: int
    text: str
    embedding: list[float]
    embedding_provider: str = "hash"


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    provider: str
    fallback_used: bool = False
    warning: dict[str, object] | None = None


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot produce vectors."""


def _is_numeric_vector(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(item, (int, float)) for item in value)


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


class BedrockEmbeddingClient:
    def __init__(
        self,
        *,
        aws_region: str,
        model_id: str,
        client: Any | None = None,
    ) -> None:
        self._aws_region = aws_region
        self._model_id = model_id
        self._client = client

    @property
    def model_id(self) -> str:
        return self._model_id

    def embed(self, text: str, dim: int) -> list[float]:
        payload: dict[str, object] = {
            "inputText": text,
            "normalize": True,
        }
        if dim > 0:
            payload["dimensions"] = dim

        client = self._get_client()
        response = client.invoke_model(
            modelId=self._model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload).encode("utf-8"),
        )
        body = response.get("body")
        if body is None:
            raise EmbeddingProviderError("Bedrock embedding response body is missing.")

        raw = body.read() if hasattr(body, "read") else body
        if isinstance(raw, bytes):
            raw_text = raw.decode("utf-8")
        elif isinstance(raw, str):
            raw_text = raw
        else:
            raise EmbeddingProviderError("Bedrock embedding response body type is unsupported.")

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise EmbeddingProviderError("Bedrock embedding response was not valid JSON.") from exc

        vector = self._extract_vector(parsed)
        return _normalize_vector(vector)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise EmbeddingProviderError("boto3 is required for Bedrock embeddings.") from exc

        self._client = boto3.client("bedrock-runtime", region_name=self._aws_region)
        return self._client

    @staticmethod
    def _extract_vector(payload: object) -> list[float]:
        if isinstance(payload, dict):
            direct = payload.get("embedding")
            if _is_numeric_vector(direct):
                return [float(item) for item in direct]

            embeddings = payload.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                first = embeddings[0]
                if _is_numeric_vector(first):
                    return [float(item) for item in first]
                if isinstance(first, dict):
                    nested = first.get("embedding")
                    if _is_numeric_vector(nested):
                        return [float(item) for item in nested]

            output = payload.get("output")
            if output is not None:
                return BedrockEmbeddingClient._extract_vector(output)

        raise EmbeddingProviderError("Bedrock embedding response did not contain an embedding vector.")


class EmbeddingService:
    _VALID_MODES = {"hash", "bedrock", "hybrid"}

    def __init__(
        self,
        *,
        mode: str,
        aws_region: str,
        bedrock_model_id: str,
        bedrock_client: BedrockEmbeddingClient | None = None,
    ) -> None:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in self._VALID_MODES:
            raise ValueError("Embedding mode must be one of: hash, bedrock, hybrid.")

        self.mode: EmbeddingMode = normalized_mode  # type: ignore[assignment]
        self._aws_region = aws_region
        self._bedrock_model_id = bedrock_model_id.strip()
        self._bedrock_client = bedrock_client
        self._bedrock_unavailable_reason: str | None = None

    def describe(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "bedrock_model_id": self._bedrock_model_id or None,
            "bedrock_available": self._bedrock_unavailable_reason is None,
        }

    def embed(self, text: str, dim: int) -> EmbeddingResult:
        if self.mode == "hash":
            return EmbeddingResult(vector=embed_text(text, dim), provider="hash")

        try:
            vector = self._embed_with_bedrock(text, dim)
            return EmbeddingResult(vector=vector, provider="bedrock")
        except Exception as exc:
            if self.mode == "bedrock":
                if isinstance(exc, EmbeddingProviderError):
                    raise
                raise EmbeddingProviderError(f"Bedrock embedding failed: {exc}") from exc

            warning = {
                "code": "embedding_provider_fallback",
                "message": "Bedrock embedding unavailable; using deterministic hash embeddings.",
                "details": {
                    "mode": self.mode,
                    "fallback_provider": "hash",
                    "error": str(exc),
                },
            }
            return EmbeddingResult(
                vector=embed_text(text, dim),
                provider="hash",
                fallback_used=True,
                warning=warning,
            )

    def _embed_with_bedrock(self, text: str, dim: int) -> list[float]:
        if not self._bedrock_model_id:
            raise EmbeddingProviderError("Bedrock embedding model ID is not configured.")
        if self._bedrock_unavailable_reason is not None:
            raise EmbeddingProviderError(self._bedrock_unavailable_reason)

        if self._bedrock_client is None:
            self._bedrock_client = BedrockEmbeddingClient(
                aws_region=self._aws_region,
                model_id=self._bedrock_model_id,
            )

        try:
            return self._bedrock_client.embed(text, dim)
        except Exception as exc:
            self._bedrock_unavailable_reason = str(exc)
            logger.warning(
                "embedding_provider_bedrock_unavailable",
                extra={
                    "event": "embedding_provider_bedrock_unavailable",
                    "mode": self.mode,
                    "model_id": self._bedrock_model_id,
                    "error": str(exc),
                },
            )
            if isinstance(exc, EmbeddingProviderError):
                raise
            raise EmbeddingProviderError(f"Bedrock embedding failed: {exc}") from exc


def _append_warning_once(warnings: list[dict[str, object]], warning: dict[str, object]) -> None:
    existing = {(item.get("code"), item.get("message")) for item in warnings}
    key = (warning.get("code"), warning.get("message"))
    if key in existing:
        return
    warnings.append(warning)


def _is_text_file(content_type: str, file_name: str) -> bool:
    if content_type.startswith("text/"):
        return True
    return Path(file_name).suffix.lower() in TEXT_FILE_EXTENSIONS


def extract_text_pages(content: bytes, content_type: str, file_name: str) -> list[ExtractedPage]:
    if not _is_text_file(content_type=content_type, file_name=file_name):
        return []

    text: str | None = None
    for encoding in ("utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        return []

    pages = text.replace("\r\n", "\n").split("\f")
    result: list[ExtractedPage] = []
    for idx, page_text in enumerate(pages, start=1):
        cleaned = page_text.strip()
        if cleaned:
            result.append(ExtractedPage(page=idx, text=cleaned))
    return result


def build_parse_report(
    *,
    content: bytes,
    content_type: str,
    file_name: str,
    pages: list[ExtractedPage],
    chunks: list[ChunkPayload],
) -> dict[str, object]:
    bytes_in = len(content)
    chars_extracted = sum(len(page.text) for page in pages)
    text_extractable = _is_text_file(content_type=content_type, file_name=file_name)
    text_density = round(chars_extracted / max(1, bytes_in), 3)

    embedding_providers: dict[str, int] = {}
    for chunk in chunks:
        embedding_providers[chunk.embedding_provider] = embedding_providers.get(chunk.embedding_provider, 0) + 1

    quality = "good"
    reason = "ok"
    if not text_extractable:
        quality = "none"
        reason = "unsupported_file_type"
    elif chars_extracted == 0:
        quality = "none"
        reason = "no_text_extracted"
    elif chars_extracted < 120 or len(chunks) == 0:
        quality = "low"
        reason = "low_extracted_text"
    elif text_density < 0.08:
        quality = "low"
        reason = "low_text_density"

    return {
        "quality": quality,
        "reason": reason,
        "text_extractable": text_extractable,
        "bytes_in": bytes_in,
        "chars_extracted": chars_extracted,
        "pages_extracted": len(pages),
        "chunks_indexed": len(chunks),
        "embedding_providers": embedding_providers,
        "text_density": text_density,
    }


def chunk_pages(
    pages: list[ExtractedPage],
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    embedding_dim: int,
    embedding_service: EmbeddingService | None = None,
    embedding_warnings: list[dict[str, object]] | None = None,
) -> list[ChunkPayload]:
    if chunk_size_chars < 1:
        raise ValueError("chunk_size_chars must be >= 1")
    if embedding_dim < 8:
        raise ValueError("embedding_dim must be >= 8")

    step = max(1, chunk_size_chars - max(0, chunk_overlap_chars))
    chunk_counter = 0
    chunks: list[ChunkPayload] = []

    for page in pages:
        start = 0
        text = page.text
        while start < len(text):
            end = min(start + chunk_size_chars, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunk_counter += 1
                embedding_result = (
                    embedding_service.embed(chunk_text, embedding_dim)
                    if embedding_service is not None
                    else EmbeddingResult(vector=embed_text(chunk_text, embedding_dim), provider="hash")
                )
                if embedding_warnings is not None and embedding_result.warning is not None:
                    _append_warning_once(embedding_warnings, embedding_result.warning)
                chunks.append(
                    ChunkPayload(
                        chunk_index=chunk_counter,
                        page=page.page,
                        text=chunk_text,
                        embedding=embedding_result.vector,
                        embedding_provider=embedding_result.provider,
                    )
                )
            if end >= len(text):
                break
            start += step

    return chunks


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def embed_text(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vector dimensions do not match")
    return float(sum(x * y for x, y in zip(a, b)))
