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
from fishrag_api.api.routes.evaluations import evaluation_job_store
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

    async def execute(
        self,
        _: object,
        params: Mapping[str, Any] | None = None,
    ) -> FakeMappingResult:
        return FakeMappingResult(self.rows)


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

    def __init__(self, hits: list[KeywordSearchHit]) -> None:
        self.hits = hits

    async def search(self, query: str, *, limit: int = 10) -> list[KeywordSearchHit]:
        return self.hits[:limit]


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
        return list(hits[:top_n])


class FakeChatClient:
    provider = "fake"
    model = "fake-chat"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, messages: Sequence[dict[str, str]]) -> str:
        self.calls += 1
        return "Generated answer [C1]."


def test_score_rag_evaluation_api_returns_aggregate_and_example_scores() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/evaluations/rag/score",
        json={
            "ks": [1, 2, 3],
            "examples": [
                {
                    "id": "hypertension-guideline",
                    "query": "How should hypertension guideline evidence be cited?",
                    "relevant_chunk_ids": ["chunk-a", "chunk-b"],
                    "retrieved_chunk_ids": ["chunk-irrelevant", "chunk-a", "chunk-b"],
                    "cited_chunk_ids": ["chunk-a"],
                    "answer": "Use the cited guideline evidence [C1].",
                },
                {
                    "id": "unknown-topic",
                    "query": "Question without knowledge base evidence",
                    "relevant_chunk_ids": [],
                    "retrieved_chunk_ids": [],
                    "cited_chunk_ids": [],
                    "answer": "",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ks"] == [1, 2, 3]
    assert body["aggregate"]["total_examples"] == 2
    assert body["aggregate"]["answered_examples"] == 1
    assert body["aggregate"]["recall_at_k"]["2"] == 0.75
    assert body["aggregate"]["citation_coverage"] == 0.75
    assert body["examples"][0]["id"] == "hypertension-guideline"
    assert body["examples"][0]["scores"]["relevant_retrieved"] == 2


def test_score_rag_evaluation_api_rejects_empty_dataset() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/evaluations/rag/score",
        json={"examples": []},
    )

    assert response.status_code == 422


def test_create_rag_evaluation_job_scores_jsonl_and_stores_history() -> None:
    evaluation_job_store.clear()
    dataset_jsonl = "\n".join(
        [
            (
                '{"id":"case-1","query":"question",'
                '"relevant_chunk_ids":["chunk-a"],'
                '"retrieved_chunk_ids":["chunk-b","chunk-a"],'
                '"cited_chunk_ids":["chunk-a"],'
                '"answer":"Answer [C1]."}'
            ),
            (
                '{"id":"case-2","query":"missing",'
                '"relevant_chunk_ids":[],'
                '"retrieved_chunk_ids":[],'
                '"cited_chunk_ids":[],'
                '"answer":""}'
            ),
        ]
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/evaluations/rag/jobs",
        json={
            "name": "Nightly RAG eval",
            "run_rag": False,
            "ks": [1, 2],
            "dataset_jsonl": dataset_jsonl,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["mode"] == "scored_dataset"
    assert body["example_count"] == 2
    assert body["report"]["aggregate"]["total_examples"] == 2
    assert body["report"]["aggregate"]["recall_at_k"]["2"] == 1.0

    job_id = body["id"]
    detail = client.get(f"/api/v1/evaluations/rag/jobs/{job_id}")
    listing = client.get("/api/v1/evaluations/rag/jobs")

    assert detail.status_code == 200
    assert detail.json()["id"] == job_id
    assert listing.status_code == 200
    assert listing.json()["jobs"][0]["id"] == job_id


def test_create_rag_evaluation_job_can_auto_run_rag_pipeline() -> None:
    evaluation_job_store.clear()
    fake_session = FakeRagSession(
        [
            {
                "chunk_id": "chunk-a",
                "document_id": "doc-1",
                "chunk_index": 0,
                "content": "vector evidence",
                "chunk_metadata": {"filename": "guide.md"},
                "filename": "guide.md",
                "content_type": "text/markdown",
                "storage_path": "uploads/guide.md",
                "score": 0.9,
            }
        ]
    )
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
        "/api/v1/evaluations/rag/jobs",
        json={
            "name": "Auto RAG eval",
            "run_rag": True,
            "use_reranker": False,
            "ks": [1],
            "examples": [
                {
                    "id": "case-1",
                    "query": "question",
                    "relevant_chunk_ids": ["chunk-a"],
                }
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["mode"] == "auto_rag"
    assert body["report"]["aggregate"]["recall_at_k"]["1"] == 1.0
    assert body["report"]["aggregate"]["citation_coverage"] == 1.0
    assert fake_chat.calls == 1


def test_create_rag_evaluation_job_rejects_invalid_jsonl() -> None:
    evaluation_job_store.clear()
    response = TestClient(create_app()).post(
        "/api/v1/evaluations/rag/jobs",
        json={
            "run_rag": False,
            "dataset_jsonl": '{"id":"case-1","query":123}',
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_rag_evaluation_jsonl"
