from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import get_session
from fishrag_api.db.models import Document
from fishrag_api.db.models import DocumentChunk as DocumentChunkModel
from fishrag_api.main import create_app
from fishrag_common.config import Settings, get_settings
from fishrag_rag.parsing import ParsedDocument
from fishrag_rag.processing import (
    build_chunked_document,
    clean_document_text,
    detect_text_sections,
    estimate_token_count,
)


class FakeChunkSession:
    def __init__(self, documents: dict[str, Document] | None = None) -> None:
        self.documents = documents or {}
        self.chunks: list[DocumentChunkModel] = []
        self.commit_count = 0

    def add(self, instance: object) -> None:
        if isinstance(instance, Document):
            self.documents[instance.id] = instance
        if isinstance(instance, DocumentChunkModel):
            self.chunks.append(instance)

    async def execute(self, _: Any) -> None:
        self.chunks.clear()

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _: object) -> None:
        return None

    async def get(self, _: type[Document], document_id: str) -> Document | None:
        return self.documents.get(document_id)


def test_clean_document_text_normalizes_spacing_and_hyphenation() -> None:
    cleaned = clean_document_text("med-\nical text\r\n\r\n\r\n第二行  \n")

    assert cleaned.text == "medical text\n\n第二行"
    assert cleaned.metadata["original_length"] > cleaned.metadata["cleaned_length"]
    assert cleaned.metadata["line_count"] == 3


def test_detect_text_sections_reads_markdown_and_numbered_headings() -> None:
    text = "# 总则\n正文\n## 适应症\n内容\n1.1 禁忌症\n更多内容"

    sections = detect_text_sections(text)

    assert [section.title for section in sections] == ["总则", "适应症", "禁忌症"]
    assert sections[1].path == ("总则", "适应症")
    assert sections[2].level == 2


def test_build_chunked_document_enriches_chunks_with_section_metadata() -> None:
    parsed = ParsedDocument(
        text=(
            "# 指南\n\n"
            + "高血压患者需要定期复查。" * 20
            + "\n\n## 用药\n"
            + "遵医嘱调整剂量。" * 10
        ),
        source_type="markdown",
        parser="markdown_text",
    )

    chunked = build_chunked_document(parsed, max_chars=120, overlap_chars=0)

    assert len(chunked.chunks) > 1
    assert chunked.metadata["section_count"] == 2
    assert chunked.chunks[0].metadata["section_title"] == "指南"
    assert isinstance(chunked.chunks[0].metadata["token_count"], int)
    assert estimate_token_count("高血压") > 0


def test_document_chunk_api_replaces_and_persists_chunks(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    storage_path = "2026/06/17/doc-1/guide.md"
    absolute_path = upload_dir / Path(storage_path)
    absolute_path.parent.mkdir(parents=True)
    absolute_path.write_text(
        "# 指南\n\n" + "高血压患者需要定期复查。" * 20 + "\n\n## 用药\n" + "遵医嘱调整剂量。" * 10,
        encoding="utf-8",
    )

    document = Document(
        id="doc-1",
        owner_user_id=None,
        filename="guide.md",
        content_type="text/markdown",
        status="uploaded",
        checksum="checksum",
        storage_path=storage_path,
        metadata_={},
    )
    fake_session = FakeChunkSession({"doc-1": document})
    app = create_app()

    async def override_session() -> AsyncIterator[FakeChunkSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_UPLOAD_DIR": str(upload_dir)})

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents/doc-1/chunks",
        json={"max_chars": 120, "overlap_chars": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["chunk_count"] == len(fake_session.chunks)
    assert body["section_count"] == 2
    assert fake_session.documents["doc-1"].status == "processing"
    assert fake_session.documents["doc-1"].metadata_["chunking"]["chunk_count"] == len(
        fake_session.chunks
    )
    assert fake_session.chunks[0].document_id == "doc-1"
    assert fake_session.chunks[0].metadata_["section_title"] == "指南"
    assert fake_session.chunks[0].token_count is not None
    assert fake_session.commit_count == 1


def test_document_chunk_api_rejects_invalid_overlap(tmp_path: Path) -> None:
    fake_session = FakeChunkSession()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeChunkSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_UPLOAD_DIR": str(tmp_path / "uploads")})

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents/doc-1/chunks",
        json={"max_chars": 100, "overlap_chars": 100},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_chunk_options"
