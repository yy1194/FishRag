from __future__ import annotations

import httpx
import pytest
from fishrag_rag.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingResponseError,
    OpenAICompatibleEmbeddingClient,
)


@pytest.mark.asyncio
async def test_openai_compatible_embedding_client_orders_vectors_by_index() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "embedding-model",
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ],
                "usage": {"prompt_tokens": 6, "total_tokens": 6},
            },
        )

    client = OpenAICompatibleEmbeddingClient(
        provider="test",
        base_url="https://embedding.example/v1",
        api_key="secret",
        model="embedding-model",
        expected_dimensions=2,
        transport=httpx.MockTransport(handler),
    )

    result = await client.embed_texts(["first", "second"])

    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.model == "embedding-model"
    assert result.dimensions == 2
    assert result.usage == {"prompt_tokens": 6, "total_tokens": 6}
    assert str(requests[0].url) == "https://embedding.example/v1/embeddings"
    assert requests[0].headers["authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_embedding_client_retries_retryable_provider_errors() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(
            200,
            json={"model": "embedding-model", "data": [{"index": 0, "embedding": [0.1, 0.2]}]},
        )

    client = OpenAICompatibleEmbeddingClient(
        provider="test",
        base_url="https://embedding.example/v1",
        api_key="secret",
        model="embedding-model",
        expected_dimensions=2,
        max_attempts=2,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    result = await client.embed_texts(["text"])

    assert result.vectors == [[0.1, 0.2]]
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_embedding_client_rejects_missing_api_key() -> None:
    client = OpenAICompatibleEmbeddingClient(
        provider="test",
        base_url="https://embedding.example/v1",
        api_key="",
        model="embedding-model",
    )

    with pytest.raises(EmbeddingConfigurationError):
        await client.embed_texts(["text"])


@pytest.mark.asyncio
async def test_embedding_client_rejects_dimension_mismatch() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
        )

    client = OpenAICompatibleEmbeddingClient(
        provider="test",
        base_url="https://embedding.example/v1",
        api_key="secret",
        model="embedding-model",
        expected_dimensions=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EmbeddingResponseError):
        await client.embed_texts(["text"])
