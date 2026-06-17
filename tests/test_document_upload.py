from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import get_session
from fishrag_api.db.models import Document
from fishrag_api.main import create_app
from fishrag_common.config import Settings, get_settings
from fishrag_rag.documents import (
    build_document_storage_path,
    can_transition_document_status,
    sanitize_document_filename,
)


class FakeDocumentSession:
    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.commit_count = 0

    def add(self, instance: object) -> None:
        if isinstance(instance, Document):
            self.documents[instance.id] = instance

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _: object) -> None:
        return None

    async def get(self, _: type[Document], document_id: str) -> Document | None:
        return self.documents.get(document_id)


def test_document_upload_persists_file_and_document_record(tmp_path: Path) -> None:
    fake_session = FakeDocumentSession()
    upload_dir = tmp_path / "uploads"
    app = create_app()

    async def override_session() -> AsyncIterator[FakeDocumentSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env(
            {
                "FISHRAG_STORAGE_DIR": str(tmp_path),
                "FISHRAG_UPLOAD_DIR": str(upload_dir),
                "FISHRAG_MAX_UPLOAD_BYTES": "1024",
            }
        )

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("../unsafe report.pdf", b"medical guideline", "application/pdf")},
        data={"metadata": '{"category":"guideline"}'},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "unsafe_report.pdf"
    assert body["status"] == "uploaded"
    assert body["content_type"] == "application/pdf"
    assert body["metadata"]["size_bytes"] == len(b"medical guideline")
    assert body["metadata"]["custom"] == {"category": "guideline"}
    assert ".." not in body["storage_path"]

    stored_path = upload_dir / Path(body["storage_path"])
    assert stored_path.read_bytes() == b"medical guideline"
    assert fake_session.documents[body["id"]].storage_path == body["storage_path"]
    assert fake_session.commit_count == 1


def test_document_status_api_allows_lifecycle_transitions(tmp_path: Path) -> None:
    fake_session = FakeDocumentSession()
    document = Document(
        id="doc-1",
        owner_user_id=None,
        filename="guide.pdf",
        content_type="application/pdf",
        status="uploaded",
        checksum="checksum",
        storage_path="2026/06/17/doc-1/guide.pdf",
        metadata_={},
    )
    fake_session.documents[document.id] = document
    app = create_app()

    async def override_session() -> AsyncIterator[FakeDocumentSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_UPLOAD_DIR": str(tmp_path / "uploads")})

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    processing_response = client.patch(
        "/api/v1/documents/doc-1/status",
        json={"status": "processing"},
    )
    indexed_response = client.patch(
        "/api/v1/documents/doc-1/status",
        json={"status": "indexed"},
    )
    invalid_response = client.patch(
        "/api/v1/documents/doc-1/status",
        json={"status": "uploaded"},
    )

    assert processing_response.status_code == 200
    assert processing_response.json()["status"] == "processing"
    assert indexed_response.status_code == 200
    assert indexed_response.json()["status"] == "indexed"
    assert invalid_response.status_code == 400
    assert invalid_response.json()["error"]["code"] == "invalid_document_status_transition"
    assert fake_session.documents["doc-1"].metadata_["status_history"] == [
        {"from": "uploaded", "to": "processing"},
        {"from": "processing", "to": "indexed"},
    ]


def test_document_upload_rejects_empty_file(tmp_path: Path) -> None:
    fake_session = FakeDocumentSession()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeDocumentSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_UPLOAD_DIR": str(tmp_path / "uploads")})

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_upload"
    assert fake_session.documents == {}


def test_document_storage_helpers_are_stable() -> None:
    assert sanitize_document_filename("../../a bad name.pdf") == "a_bad_name.pdf"
    assert sanitize_document_filename("") == "upload.bin"

    storage_path = build_document_storage_path(
        "doc/../1",
        "report.pdf",
    )

    assert storage_path.endswith("/doc_1/report.pdf")
    assert can_transition_document_status("uploaded", "processing")
    assert not can_transition_document_status("indexed", "uploaded")

    with pytest.raises(ValueError):
        build_document_storage_path("", "report.pdf")
