from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import (
    get_embedding_client,
    get_keyword_index_client,
    get_reranker_client,
    get_session,
)
from fishrag_api.main import create_app
from fishrag_common.config import Settings, get_settings
from fishrag_rag.embeddings import EmbeddingBatch
from fishrag_rag.keyword_index import KeywordSearchHit
from fishrag_rag.retrieval import RetrievalHit


class FakeMappingResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappingResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeAgentSession:
    async def execute(
        self,
        _: object,
        params: Mapping[str, Any] | None = None,
    ) -> FakeMappingResult:
        return FakeMappingResult(
            [
                {
                    "chunk_id": "chunk-vector",
                    "document_id": "doc-1",
                    "chunk_index": 0,
                    "content": "vector evidence",
                    "chunk_metadata": {"filename": "guide.md"},
                    "filename": "guide.md",
                    "content_type": "text/markdown",
                    "storage_path": "uploads/guide.md",
                    "score": 0.81,
                }
            ]
        )


class FakeEmbeddingClient:
    provider = "fake"
    model = "fake-embedding"

    async def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            vectors=[[0.1, 0.2] for _ in texts],
            model=self.model,
            dimensions=2,
        )


class FakeKeywordIndexClient:
    index_name = "fishrag_chunks"

    async def search(self, query: str, *, limit: int = 10) -> list[KeywordSearchHit]:
        return [
            KeywordSearchHit(
                chunk_id="chunk-keyword",
                document_id="doc-2",
                chunk_index=1,
                content=f"keyword evidence for {query}",
                score=9.0,
                metadata={"filename": "keyword.md"},
            )
        ][:limit]


class FakeRerankerClient:
    provider = "fake"
    model = "fake-reranker"

    async def rerank(
        self,
        *,
        query: str,
        hits: Sequence[RetrievalHit],
        top_n: int,
    ) -> list[RetrievalHit]:
        return list(hits)[:top_n]


def test_agent_tools_api_lists_capabilities_without_loading_skill_instructions() -> None:
    response = TestClient(create_app()).get("/api/v1/agent/tools")

    assert response.status_code == 200
    body = response.json()
    assert "rag_search" in body["tools"]
    assert any(subagent["name"] == "rag_researcher" for subagent in body["subagents"])
    assert any(skill["name"] == "rag_answering" for skill in body["skills"])
    assert "instructions" not in body["skills"][0]


def test_agent_run_api_executes_tools_and_rag_search() -> None:
    app = create_app()

    async def override_session() -> AsyncIterator[FakeAgentSession]:
        yield FakeAgentSession()

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_EMBEDDING_DIMENSIONS": "2"})

    def override_embedding_client() -> FakeEmbeddingClient:
        return FakeEmbeddingClient()

    def override_keyword_client() -> FakeKeywordIndexClient:
        return FakeKeywordIndexClient()

    def override_reranker_client() -> FakeRerankerClient:
        return FakeRerankerClient()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_client] = override_embedding_client
    app.dependency_overrides[get_keyword_index_client] = override_keyword_client
    app.dependency_overrides[get_reranker_client] = override_reranker_client
    client = TestClient(app)

    response = client.post(
        "/api/v1/agent/sessions/agent-api-session/run",
        json={
            "input": "请检索高血压证据",
            "tool_calls": [
                {
                    "name": "write_todos",
                    "arguments": {
                        "todos": [
                            {
                                "id": "1",
                                "content": "检索知识库",
                                "status": "completed",
                            }
                        ]
                    },
                },
                {
                    "name": "remember",
                    "arguments": {"key": "topic", "value": "高血压"},
                },
                {
                    "name": "task",
                    "arguments": {
                        "subagent": "rag_researcher",
                        "description": "整理证据",
                    },
                },
                {
                    "name": "load_skill",
                    "arguments": {"name": "rag_answering"},
                },
                {
                    "name": "rag_search",
                    "arguments": {
                        "query": "高血压",
                        "limit": 2,
                        "use_reranker": False,
                    },
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["tool_results"][0]["output"]["stats"]["total"] == 1
    assert body["tool_results"][1]["output"]["key"] == "topic"
    assert body["tool_results"][2]["output"]["results"][0]["subagent"] == "rag_researcher"
    assert body["tool_results"][3]["output"]["metadata"]["name"] == "rag_answering"
    assert body["tool_results"][4]["output"]["citations"][0]["id"] == "C1"
    assert "rag_search" in body["available_tools"]
