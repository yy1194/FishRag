from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import (
    get_chat_client,
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


class FakeRagSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed_params: dict[str, Any] = {}

    async def execute(
        self,
        _: object,
        params: Mapping[str, Any] | None = None,
    ) -> FakeMappingResult:
        self.executed_params = dict(params or {})
        return FakeMappingResult(self.rows)


class FakeEmbeddingClient:
    provider = "fake"
    model = "fake-embedding"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        batch = list(texts)
        self.calls.append(batch)
        return EmbeddingBatch(
            vectors=[[0.1, 0.2] for _ in batch],
            model=self.model,
            dimensions=2,
        )


class FakeKeywordIndexClient:
    index_name = "fishrag_chunks"

    def __init__(self, hits: list[KeywordSearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, limit: int = 10) -> list[KeywordSearchHit]:
        self.calls.append((query, limit))
        return self.hits[:limit]


class FakeRerankerClient:
    provider = "fake"
    model = "fake-reranker"

    def __init__(self) -> None:
        self.calls = 0

    async def rerank(
        self,
        *,
        query: str,
        hits: Sequence[RetrievalHit],
        top_n: int,
    ) -> list[RetrievalHit]:
        self.calls += 1
        reranked: list[RetrievalHit] = []
        for index, hit in enumerate(reversed(list(hits))):
            if index >= top_n:
                break
            metadata = dict(hit.metadata)
            metadata["reranker_query"] = query
            reranked.append(
                RetrievalHit(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    chunk_index=hit.chunk_index,
                    content=hit.content,
                    score=1.0 - index * 0.1,
                    source="reranker",
                    metadata=metadata,
                )
            )
        return reranked


class FakeChatClient:
    provider = "fake"
    model = "fake-chat"

    def __init__(self, *, answer: str = "Generated answer [C1].") -> None:
        self.answer = answer
        self.calls = 0
        self.messages: list[dict[str, str]] = []

    async def complete(self, *, messages: Sequence[dict[str, str]]) -> str:
        self.calls += 1
        self.messages = list(messages)
        return self.answer


def test_rag_search_api_runs_hybrid_search_with_reranker() -> None:
    fake_session = FakeRagSession(
        [
            {
                "chunk_id": "chunk-vector",
                "document_id": "doc-1",
                "chunk_index": 0,
                "content": "vector evidence",
                "chunk_metadata": {"filename": "vector.md"},
                "filename": "vector.md",
                "content_type": "text/markdown",
                "storage_path": "uploads/vector.md",
                "score": 0.72,
            }
        ]
    )
    fake_embedding = FakeEmbeddingClient()
    fake_keyword = FakeKeywordIndexClient(
        [
            KeywordSearchHit(
                chunk_id="chunk-keyword",
                document_id="doc-2",
                chunk_index=1,
                content="keyword evidence",
                score=12.0,
                metadata={"filename": "keyword.md"},
            )
        ]
    )
    fake_reranker = FakeRerankerClient()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeRagSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_EMBEDDING_DIMENSIONS": "2"})

    def override_embedding_client() -> FakeEmbeddingClient:
        return fake_embedding

    def override_keyword_client() -> FakeKeywordIndexClient:
        return fake_keyword

    def override_reranker_client() -> FakeRerankerClient:
        return fake_reranker

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_client] = override_embedding_client
    app.dependency_overrides[get_keyword_index_client] = override_keyword_client
    app.dependency_overrides[get_reranker_client] = override_reranker_client

    response = TestClient(app).post(
        "/api/v1/rag/search",
        json={"query": "question", "limit": 2, "reranker_top_n": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["hits"][0]["source"] == "reranker"
    assert body["hits"][0]["chunk_id"] == "chunk-keyword"
    assert body["citations"][0]["id"] == "C1"
    assert fake_session.executed_params["query_vector"] == "[0.1,0.2]"
    assert fake_keyword.calls == [("question", 20)]
    assert fake_reranker.calls == 1


def test_rag_answer_api_returns_no_evidence_without_calling_chat() -> None:
    fake_session = FakeRagSession([])
    fake_embedding = FakeEmbeddingClient()
    fake_keyword = FakeKeywordIndexClient([])
    fake_reranker = FakeRerankerClient()
    fake_chat = FakeChatClient()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeRagSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_EMBEDDING_DIMENSIONS": "2"})

    def override_embedding_client() -> FakeEmbeddingClient:
        return fake_embedding

    def override_keyword_client() -> FakeKeywordIndexClient:
        return fake_keyword

    def override_reranker_client() -> FakeRerankerClient:
        return fake_reranker

    def override_chat_client() -> FakeChatClient:
        return fake_chat

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_client] = override_embedding_client
    app.dependency_overrides[get_keyword_index_client] = override_keyword_client
    app.dependency_overrides[get_reranker_client] = override_reranker_client
    app.dependency_overrides[get_chat_client] = override_chat_client

    response = TestClient(app).post(
        "/api/v1/rag/answer",
        json={"query": "missing", "use_reranker": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert not body["is_answered"]
    assert body["citations"] == []
    assert "没有检索到足够证据" in body["answer"]
    assert fake_chat.calls == 0


def test_rag_answer_api_adds_medical_safety_disclaimer_for_high_risk_answer() -> None:
    fake_session = FakeRagSession(
        [
            {
                "chunk_id": "chunk-vector",
                "document_id": "doc-1",
                "chunk_index": 0,
                "content": "evidence",
                "chunk_metadata": {"filename": "guide.md"},
                "filename": "guide.md",
                "content_type": "text/markdown",
                "storage_path": "uploads/guide.md",
                "score": 0.8,
            }
        ]
    )
    fake_embedding = FakeEmbeddingClient()
    fake_keyword = FakeKeywordIndexClient([])
    fake_reranker = FakeRerankerClient()
    fake_chat = FakeChatClient(answer="资料提示需要遵医嘱调整剂量。[C1]")
    app = create_app()

    async def override_session() -> AsyncIterator[FakeRagSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_EMBEDDING_DIMENSIONS": "2"})

    def override_embedding_client() -> FakeEmbeddingClient:
        return fake_embedding

    def override_keyword_client() -> FakeKeywordIndexClient:
        return fake_keyword

    def override_reranker_client() -> FakeRerankerClient:
        return fake_reranker

    def override_chat_client() -> FakeChatClient:
        return fake_chat

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_client] = override_embedding_client
    app.dependency_overrides[get_keyword_index_client] = override_keyword_client
    app.dependency_overrides[get_reranker_client] = override_reranker_client
    app.dependency_overrides[get_chat_client] = override_chat_client

    response = TestClient(app).post(
        "/api/v1/rag/answer",
        json={"query": "这个药的剂量怎么调整？", "use_reranker": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_answered"]
    assert body["safety"]["high_risk"]
    assert "不能替代医生诊断" in body["answer"]
