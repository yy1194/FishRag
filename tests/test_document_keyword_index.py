from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import get_keyword_index_client, get_session
from fishrag_api.db.models import Document
from fishrag_api.db.models import DocumentChunk as DocumentChunkModel
from fishrag_api.main import create_app
from fishrag_rag.keyword_index import KeywordIndexBatchResult, KeywordIndexDocument


class FakeScalarResult:
    def __init__(self, chunks: list[DocumentChunkModel]) -> None:
        self.chunks = chunks

    def scalars(self) -> FakeScalarResult:
        return self

    def all(self) -> list[DocumentChunkModel]:
        return sorted(self.chunks, key=lambda chunk: chunk.chunk_index)


class FakeKeywordIndexSession:
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


class FakeKeywordIndexClient:
    index_name = "fishrag_chunks"

    def __init__(self, *, errors: list[str] | None = None) -> None:
        self.errors = errors or []
        self.ensure_called = False
        self.documents: list[KeywordIndexDocument] = []
        self.refresh = False

    async def ensure_index(self) -> None:
        self.ensure_called = True

    async def bulk_index_documents(
        self,
        documents: Sequence[KeywordIndexDocument],
        *,
        refresh: bool = False,
    ) -> KeywordIndexBatchResult:
        self.documents = list(documents)
        self.refresh = refresh
        return KeywordIndexBatchResult(
            index_name=self.index_name,
            indexed_count=len(self.documents) - len(self.errors),
            errors=self.errors,
        )


def _document() -> Document:
    return Document(
        id="doc-1",
        owner_user_id=None,
        filename="guide.md",
        content_type="text/markdown",
        status="processing",
        checksum="checksum",
        storage_path="2026/06/18/doc-1/guide.md",
        metadata_={},
    )


def _chunks() -> list[DocumentChunkModel]:
    return [
        DocumentChunkModel(
            id="chunk-1",
            document_id="doc-1",
            chunk_index=0,
            content="高血压诊疗指南",
            embedding=[0.1, 0.2, 0.3],
            token_count=8,
            metadata_={"section_title": "指南", "section_path": ["指南"]},
        ),
        DocumentChunkModel(
            id="chunk-2",
            document_id="doc-1",
            chunk_index=1,
            content="用药建议",
            embedding=[0.4, 0.5, 0.6],
            token_count=4,
            metadata_={"section_title": "用药"},
        ),
    ]


def test_document_keyword_index_api_indexes_chunks_and_marks_indexed() -> None:
    document = _document()
    fake_session = FakeKeywordIndexSession(document, _chunks())
    fake_client = FakeKeywordIndexClient()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeKeywordIndexSession]:
        yield fake_session

    def override_keyword_client() -> FakeKeywordIndexClient:
        return fake_client

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_keyword_index_client] = override_keyword_client
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents/doc-1/keyword-index",
        json={"refresh": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "indexed"
    assert body["indexed_chunk_count"] == 2
    assert body["error_count"] == 0
    assert fake_client.ensure_called
    assert fake_client.refresh
    assert fake_client.documents[0].id == "doc-1:chunk-1"
    assert fake_client.documents[0].metadata["filename"] == "guide.md"
    assert fake_client.documents[0].metadata["token_count"] == 8
    assert document.status == "indexed"
    assert document.metadata_["keyword_index"]["indexed_chunk_count"] == 2
    assert fake_session.commit_count == 1


def test_document_keyword_index_api_returns_bulk_errors_without_marking_indexed() -> None:
    document = _document()
    fake_session = FakeKeywordIndexSession(document, _chunks())
    fake_client = FakeKeywordIndexClient(errors=["bulk error"])
    app = create_app()

    async def override_session() -> AsyncIterator[FakeKeywordIndexSession]:
        yield fake_session

    def override_keyword_client() -> FakeKeywordIndexClient:
        return fake_client

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_keyword_index_client] = override_keyword_client
    client = TestClient(app)

    response = client.post("/api/v1/documents/doc-1/keyword-index", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    assert response.json()["error_count"] == 1
    assert document.status == "processing"
    assert fake_session.commit_count == 0
