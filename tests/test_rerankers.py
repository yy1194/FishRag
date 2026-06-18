from __future__ import annotations

import httpx
import pytest
from fishrag_rag.rerankers import (
    OpenAICompatibleRerankerClient,
    RerankerConfigurationError,
    RerankerResponseError,
)
from fishrag_rag.retrieval import RetrievalHit


def _hits() -> list[RetrievalHit]:
    return [
        RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            chunk_index=0,
            content="first evidence",
            score=0.3,
            source="hybrid",
        ),
        RetrievalHit(
            chunk_id="chunk-2",
            document_id="doc-1",
            chunk_index=1,
            content="second evidence",
            score=0.2,
            source="hybrid",
        ),
    ]


@pytest.mark.asyncio
async def test_openai_compatible_reranker_orders_hits_by_relevance_score() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.43},
                ]
            },
        )

    client = OpenAICompatibleRerankerClient(
        provider="test",
        base_url="https://reranker.example/v1",
        api_key="secret",
        model="reranker-model",
        transport=httpx.MockTransport(handler),
    )

    result = await client.rerank(query="question", hits=_hits(), top_n=2)

    assert [hit.chunk_id for hit in result] == ["chunk-2", "chunk-1"]
    assert result[0].source == "reranker"
    assert result[0].score == 0.91
    assert result[0].metadata["reranker_score"] == 0.91
    assert str(requests[0].url) == "https://reranker.example/v1/rerank"
    assert requests[0].headers["authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_reranker_rejects_missing_api_key() -> None:
    client = OpenAICompatibleRerankerClient(
        provider="test",
        base_url="https://reranker.example/v1",
        api_key="",
        model="reranker-model",
    )

    with pytest.raises(RerankerConfigurationError):
        await client.rerank(query="question", hits=_hits(), top_n=2)


@pytest.mark.asyncio
async def test_reranker_rejects_out_of_range_index() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"index": 10, "score": 0.7}]})

    client = OpenAICompatibleRerankerClient(
        provider="test",
        base_url="https://reranker.example/v1",
        api_key="secret",
        model="reranker-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RerankerResponseError):
        await client.rerank(query="question", hits=_hits(), top_n=1)
