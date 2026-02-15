import pytest

from app.retrieval import (
    EmbeddingProviderError,
    EmbeddingService,
    ExtractedPage,
    chunk_pages,
)


class FailingBedrockClient:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str, dim: int) -> list[float]:
        self.calls += 1
        raise EmbeddingProviderError("simulated bedrock failure")


class SuccessfulBedrockClient:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str, dim: int) -> list[float]:
        self.calls += 1
        return [0.5 for _ in range(dim)]


def test_embedding_service_hash_mode_returns_hash_vectors() -> None:
    service = EmbeddingService(
        mode="hash",
        aws_region="us-east-1",
        bedrock_model_id="unused",
    )

    result = service.embed("households served", 32)

    assert result.provider == "hash"
    assert result.fallback_used is False
    assert result.warning is None
    assert len(result.vector) == 32


def test_embedding_service_hybrid_falls_back_and_trips_circuit_breaker() -> None:
    failing_client = FailingBedrockClient()
    service = EmbeddingService(
        mode="hybrid",
        aws_region="us-east-1",
        bedrock_model_id="test-model",
        bedrock_client=failing_client,  # type: ignore[arg-type]
    )

    first = service.embed("households served", 32)
    second = service.embed("grant outcomes", 32)

    assert first.provider == "hash"
    assert first.fallback_used is True
    assert first.warning is not None
    assert first.warning.get("code") == "embedding_provider_fallback"
    assert second.provider == "hash"
    assert second.fallback_used is True
    assert failing_client.calls == 1


def test_embedding_service_bedrock_mode_raises_on_failure() -> None:
    service = EmbeddingService(
        mode="bedrock",
        aws_region="us-east-1",
        bedrock_model_id="test-model",
        bedrock_client=FailingBedrockClient(),  # type: ignore[arg-type]
    )

    with pytest.raises(EmbeddingProviderError):
        service.embed("households served", 32)


def test_embedding_service_bedrock_mode_returns_bedrock_vector_on_success() -> None:
    successful_client = SuccessfulBedrockClient()
    service = EmbeddingService(
        mode="bedrock",
        aws_region="us-east-1",
        bedrock_model_id="test-model",
        bedrock_client=successful_client,  # type: ignore[arg-type]
    )

    result = service.embed("households served", 32)

    assert result.provider == "bedrock"
    assert result.fallback_used is False
    assert result.warning is None
    assert len(result.vector) == 32
    assert successful_client.calls == 1


def test_chunk_pages_records_embedding_provider_and_warning_in_hybrid_fallback() -> None:
    failing_client = FailingBedrockClient()
    service = EmbeddingService(
        mode="hybrid",
        aws_region="us-east-1",
        bedrock_model_id="test-model",
        bedrock_client=failing_client,  # type: ignore[arg-type]
    )
    warnings: list[dict[str, object]] = []

    chunks = chunk_pages(
        pages=[ExtractedPage(page=1, text="Need statement evidence for households served")],
        chunk_size_chars=120,
        chunk_overlap_chars=20,
        embedding_dim=32,
        embedding_service=service,
        embedding_warnings=warnings,
    )

    assert len(chunks) == 1
    assert chunks[0].embedding_provider == "hash"
    assert len(warnings) == 1
    assert warnings[0].get("code") == "embedding_provider_fallback"
