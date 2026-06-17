from __future__ import annotations

import zipfile
from collections.abc import AsyncIterator
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import get_session
from fishrag_api.db.models import Document
from fishrag_api.main import create_app
from fishrag_common.config import Settings, get_settings
from fishrag_rag.parsing import (
    UnsupportedDocumentFormatError,
    infer_document_type,
    parse_csv_file,
    parse_docx_file,
    parse_markdown_file,
    parse_pdf_file,
    parse_text_file,
)

fitz: Any = import_module("fitz")


class FakeDocumentSession:
    def __init__(self, documents: dict[str, Document] | None = None) -> None:
        self.documents = documents or {}
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


def test_parse_text_file_reads_utf8_sig(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes("\ufeff第一行\r\n第二行".encode("utf-8"))

    parsed = parse_text_file(path)

    assert parsed.source_type == "text"
    assert parsed.parser == "plain_text"
    assert parsed.text == "第一行\n第二行"
    assert parsed.metadata["line_count"] == 2


def test_parse_markdown_file_extracts_sections(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text(
        "---\ntitle: demo\n---\n# 高血压指南\n\n## 用药建议\n内容",
        encoding="utf-8",
    )

    parsed = parse_markdown_file(path)

    assert parsed.source_type == "markdown"
    assert parsed.text.startswith("# 高血压指南")
    assert parsed.metadata["sections"] == [
        {"level": 1, "title": "高血压指南", "line": 1},
        {"level": 2, "title": "用药建议", "line": 3},
    ]


def test_parse_csv_file_converts_rows_to_text(tmp_path: Path) -> None:
    path = tmp_path / "drugs.csv"
    path.write_text("name,dose\nAspirin,100mg\nMetformin,500mg\n", encoding="utf-8")

    parsed = parse_csv_file(path)

    assert parsed.source_type == "csv"
    assert "name: Aspirin; dose: 100mg" in parsed.text
    assert parsed.metadata == {"row_count": 2, "column_count": 2, "has_header": True}


def test_parse_docx_file_reads_document_xml(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    document_xml = """
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>第一段</w:t></w:r></w:p>
        <w:p><w:r><w:t>第二段</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    parsed = parse_docx_file(path)

    assert parsed.source_type == "docx"
    assert parsed.text == "第一段\n第二段"
    assert parsed.metadata["paragraph_count"] == 2


def test_parse_pdf_file_reads_real_pdf_text(tmp_path: Path) -> None:
    path = tmp_path / "guide.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "PDF hypertension guideline")
    document.save(path)
    document.close()

    parsed = parse_pdf_file(path)

    assert parsed.source_type == "pdf"
    assert parsed.parser == "pymupdf"
    assert "PDF hypertension guideline" in parsed.text
    assert parsed.metadata["page_count"] == 1


def test_infer_document_type_rejects_legacy_doc(tmp_path: Path) -> None:
    path = tmp_path / "legacy.doc"

    try:
        infer_document_type(path)
    except UnsupportedDocumentFormatError as exc:
        assert "Legacy .doc" in str(exc)
    else:
        raise AssertionError("Expected legacy .doc to be unsupported.")


def test_document_parse_api_updates_metadata_and_status(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    storage_path = "2026/06/17/doc-1/guide.md"
    absolute_path = upload_dir / Path(storage_path)
    absolute_path.parent.mkdir(parents=True)
    absolute_path.write_text("# 指南\n\n正文内容", encoding="utf-8")

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
    fake_session = FakeDocumentSession({"doc-1": document})
    app = create_app()

    async def override_session() -> AsyncIterator[FakeDocumentSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_UPLOAD_DIR": str(upload_dir)})

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    response = client.post("/api/v1/documents/doc-1/parse?preview_chars=4")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["source_type"] == "markdown"
    assert body["parser"] == "markdown_text"
    assert body["text_preview"] == "# 指南"
    assert fake_session.documents["doc-1"].status == "processing"
    assert fake_session.documents["doc-1"].metadata_["parse"]["source_type"] == "markdown"
    assert fake_session.documents["doc-1"].metadata_["status_history"] == [
        {"from": "uploaded", "to": "processing"}
    ]
    assert fake_session.commit_count == 1


def test_document_parse_api_handles_real_pdf(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    storage_path = "2026/06/18/doc-pdf/guide.pdf"
    absolute_path = upload_dir / Path(storage_path)
    absolute_path.parent.mkdir(parents=True)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "PDF diagnosis workflow")
    pdf.save(absolute_path)
    pdf.close()

    document = Document(
        id="doc-pdf",
        owner_user_id=None,
        filename="guide.pdf",
        content_type="application/pdf",
        status="uploaded",
        checksum="checksum",
        storage_path=storage_path,
        metadata_={},
    )
    fake_session = FakeDocumentSession({"doc-pdf": document})
    app = create_app()

    async def override_session() -> AsyncIterator[FakeDocumentSession]:
        yield fake_session

    def override_settings() -> Settings:
        return Settings.from_env({"FISHRAG_UPLOAD_DIR": str(upload_dir)})

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    response = client.post("/api/v1/documents/doc-pdf/parse?preview_chars=100")

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "pdf"
    assert body["parser"] == "pymupdf"
    assert "PDF diagnosis workflow" in body["text_preview"]
    assert fake_session.documents["doc-pdf"].metadata_["parse"]["metadata"]["page_count"] == 1
