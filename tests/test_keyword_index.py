from __future__ import annotations

import json

import httpx
import pytest
from fishrag_rag.keyword_index import (
    KeywordIndexConfigurationError,
    KeywordIndexDocument,
    OpenSearchKeywordIndexClient,
)


@pytest.mark.asyncio
async def test_opensearch_keyword_index_client_creates_index_and_bulk_indexes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "HEAD":
            return httpx.Response(404)
        if request.method == "PUT":
            return httpx.Response(200, json={"acknowledged": True})
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "errors": False,
                    "items": [{"index": {"status": 201}}],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenSearchKeywordIndexClient(
        base_url="http://opensearch:9200",
        index_name="fishrag_chunks",
        transport=httpx.MockTransport(handler),
    )

    await client.ensure_index()
    result = await client.bulk_index_documents(
        [
            KeywordIndexDocument(
                id="doc-1:chunk-1",
                document_id="doc-1",
                chunk_id="chunk-1",
                chunk_index=0,
                content="高血压诊疗指南",
                metadata={"section_title": "指南"},
            )
        ],
        refresh=True,
    )

    assert result.indexed_count == 1
    assert result.errors == []
    assert requests[0].method == "HEAD"
    assert str(requests[0].url) == "http://opensearch:9200/fishrag_chunks"
    assert requests[1].method == "PUT"
    assert requests[2].method == "POST"
    assert str(requests[2].url) == "http://opensearch:9200/_bulk?refresh=true"
    body_lines = requests[2].content.decode("utf-8").splitlines()
    assert json.loads(body_lines[0]) == {
        "index": {"_index": "fishrag_chunks", "_id": "doc-1:chunk-1"}
    }
    assert json.loads(body_lines[1])["content"] == "高血压诊疗指南"


@pytest.mark.asyncio
async def test_keyword_index_client_reports_bulk_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "errors": True,
                    "items": [{"index": {"error": {"type": "mapper_parsing_exception"}}}],
                },
            )
        return httpx.Response(200)

    client = OpenSearchKeywordIndexClient(
        base_url="http://opensearch:9200",
        index_name="fishrag_chunks",
        transport=httpx.MockTransport(handler),
    )

    result = await client.bulk_index_documents(
        [
            KeywordIndexDocument(
                id="doc-1:chunk-1",
                document_id="doc-1",
                chunk_id="chunk-1",
                chunk_index=0,
                content="text",
            )
        ]
    )

    assert result.indexed_count == 0
    assert "mapper_parsing_exception" in result.errors[0]


@pytest.mark.asyncio
async def test_keyword_index_client_rejects_missing_index_name() -> None:
    client = OpenSearchKeywordIndexClient(base_url="http://opensearch:9200", index_name="")

    with pytest.raises(KeywordIndexConfigurationError):
        await client.ensure_index()
