from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import get_embedding_client, get_session
from fishrag_api.db.models import Document
from fishrag_api.db.models import DocumentChunk as DocumentChunkModel
from fishrag_api.main import create_app
from fishrag_common.config import Settings, get_settings
from fishrag_rag.embeddings import EmbeddingBatch


class FakeScalarResult:
    def __init__(self, chunks: list[DocumentChunkModel]) -> None:
        self.chunks = chunks

    def scalars(self) -> FakeScalarResult:
        return self

    def all(self) -> list[DocumentChunkModel]:
        return sorted(self.chunks, key=lambda chunk: chunk.chunk_index)


class FakeEmbeddingSession:
    def __init__(
        self,
        document: Document,
        chunks: list[DocumentChunkModel],
    ) -> None:
        self.document = document
        self.chunks = chunks
        self.commit_count = 0

    async def get(self, _: type[Document], document_id: str) -> Document | None:
        if document_id == self.document.id:
            return self.document
        return None

    async def execute(self, _: object) -> FakeScalarResult:
        return FakeScalarResult(self.chunks)

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _: object) -> None:
        return None


class FakeEmbeddingClient:
    provider = "fake"
    model = "fake-embedding"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        batch = list(texts)
        self.calls.append(batch)
        vectors = [
            [float(index), float(index + 1), float(index + 2)]
            for index, _ in enumerate(batch)
        ]
        return EmbeddingBatch(
            vectors=vectors,
            model=self.model,
            dimensions=3,
            usage={"total_tokens": sum(len(text) for text in batch)},
        )


def test_document_embedding_api_embeds_chunks_in_batches() -> None:
    document = Document(
        id="doc-1",
        owner_user_id=None,
        filename="guide.md",
        content_type="text/markdown",
        status="processing",
        checksum="checksum",
        storage_path="2026/06/17/doc-1/guide.md",
        metadata_={},
    )
    chunks = [
        DocumentChunkModel(
            id="chunk-1",
            document_id="doc-1",
            chunk_index=0,
            content="第一段",
            embedding=None,
            token_count=3,
            metadata_={},
        ),
        DocumentChunkModel(
            id="chunk-2",
            document_id="doc-1",
            chunk_index=1,
            content="第二段",
            embedding=None,
            token_count=3,
            metadata_={},
        ),
    ]
    fake_session = FakeEmbeddingSession(document, chunks)
    fake_client = FakeEmbeddingClient()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeEmbeddingSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env(
            {
                "FISHRAG_EMBEDDING_PROVIDER": "fake",
                "FISHRAG_EMBEDDING_MODEL": "fake-embedding",
                "FISHRAG_EMBEDDING_DIMENSIONS": "3",
            }
        )

    def override_embedding_client() -> FakeEmbeddingClient:
        return fake_client

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_client] = override_embedding_client
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents/doc-1/embeddings",
        json={"batch_size": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["embedded_chunk_count"] == 2
    assert body["skipped_chunk_count"] == 0
    assert body["dimensions"] == 3
    assert len(fake_client.calls) == 2
    assert chunks[0].embedding == [0.0, 1.0, 2.0]
    assert chunks[0].metadata_["embedding"]["model"] == "fake-embedding"
    assert document.metadata_["embedding"]["embedded_chunk_count"] == 2
    assert fake_session.commit_count == 1


def test_document_embedding_api_skips_existing_embeddings() -> None:
    document = Document(
        id="doc-1",
        owner_user_id=None,
        filename="guide.md",
        content_type="text/markdown",
        status="processing",
        checksum="checksum",
        storage_path="2026/06/17/doc-1/guide.md",
        metadata_={},
    )
    chunks = [
        DocumentChunkModel(
            id="chunk-1",
            document_id="doc-1",
            chunk_index=0,
            content="第一段",
            embedding=[1.0, 2.0, 3.0],
            token_count=3,
            metadata_={},
        )
    ]
    fake_session = FakeEmbeddingSession(document, chunks)
    fake_client = FakeEmbeddingClient()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeEmbeddingSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_EMBEDDING_DIMENSIONS": "3"})

    def override_embedding_client() -> FakeEmbeddingClient:
        return fake_client

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_client] = override_embedding_client
    client = TestClient(app)

    response = client.post("/api/v1/documents/doc-1/embeddings", json={})

    assert response.status_code == 200
    assert response.json()["embedded_chunk_count"] == 0
    assert response.json()["skipped_chunk_count"] == 1
    assert fake_client.calls == []
    assert fake_session.commit_count == 0
