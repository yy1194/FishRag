from __future__ import annotations

import csv
import importlib
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


class DocumentParseError(Exception):
    """Raised when a document cannot be parsed."""


class UnsupportedDocumentFormatError(DocumentParseError):
    """Raised when no parser is available for a document format."""


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    source_type: str
    parser: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_length(self) -> int:
        return len(self.text)


def parse_document_file(
    path: Path,
    *,
    content_type: str | None = None,
    filename: str | None = None,
) -> ParsedDocument:
    source_type = infer_document_type(path, content_type=content_type, filename=filename)
    if source_type == "text":
        return parse_text_file(path)
    if source_type == "markdown":
        return parse_markdown_file(path)
    if source_type == "csv":
        return parse_csv_file(path)
    if source_type == "docx":
        return parse_docx_file(path)
    if source_type == "pdf":
        return parse_pdf_file(path)
    raise UnsupportedDocumentFormatError(f"Unsupported document format: {source_type}")


def infer_document_type(
    path: Path,
    *,
    content_type: str | None = None,
    filename: str | None = None,
) -> str:
    suffix = _document_suffix(path, filename)
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()

    if suffix in {".txt", ".text"} or normalized_content_type.startswith("text/plain"):
        return "text"
    if suffix in {".md", ".markdown"} or normalized_content_type in {
        "text/markdown",
        "text/x-markdown",
    }:
        return "markdown"
    if suffix == ".csv" or normalized_content_type in {"text/csv", "application/csv"}:
        return "csv"
    if suffix == ".docx" or normalized_content_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return "docx"
    if suffix == ".pdf" or normalized_content_type == "application/pdf":
        return "pdf"
    if suffix == ".doc":
        raise UnsupportedDocumentFormatError("Legacy .doc files are not supported yet.")
    raise UnsupportedDocumentFormatError("Unsupported document format.")


def parse_text_file(path: Path) -> ParsedDocument:
    text = _read_text(path)
    normalized = _normalize_text(text)
    _ensure_text(normalized)
    return ParsedDocument(
        text=normalized,
        source_type="text",
        parser="plain_text",
        metadata={"line_count": _line_count(normalized)},
    )


def parse_markdown_file(path: Path) -> ParsedDocument:
    text = _strip_frontmatter(_normalize_text(_read_text(path)))
    _ensure_text(text)
    sections = _markdown_sections(text)
    return ParsedDocument(
        text=text,
        source_type="markdown",
        parser="markdown_text",
        metadata={"line_count": _line_count(text), "sections": sections},
    )


def parse_csv_file(path: Path) -> ParsedDocument:
    raw_text = _read_text(path)
    rows = list(csv.reader(io.StringIO(raw_text)))
    rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise DocumentParseError("CSV file has no readable rows.")

    headers = rows[0]
    data_rows = rows[1:] if len(rows) > 1 else rows
    has_header = len(rows) > 1 and any(headers)
    lines: list[str] = []
    for index, row in enumerate(data_rows, start=1):
        if has_header:
            pairs = []
            for column_index, value in enumerate(row):
                header = (
                    headers[column_index]
                    if column_index < len(headers)
                    else f"column_{column_index}"
                )
                pairs.append(f"{header}: {value}")
            lines.append(f"row {index}: " + "; ".join(pairs))
        else:
            lines.append(f"row {index}: " + "; ".join(row))

    text = _normalize_text("\n".join(lines))
    _ensure_text(text)
    return ParsedDocument(
        text=text,
        source_type="csv",
        parser="csv_reader",
        metadata={
            "row_count": len(data_rows),
            "column_count": max(len(row) for row in rows),
            "has_header": has_header,
        },
    )


def parse_docx_file(path: Path) -> ParsedDocument:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise DocumentParseError("DOCX file is invalid or missing word/document.xml.") from exc

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ElementTree.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        text_parts = [
            text_node.text or "" for text_node in paragraph.iter(f"{namespace}t")
        ]
        paragraph_text = "".join(text_parts).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    text = _normalize_text("\n".join(paragraphs))
    _ensure_text(text)
    return ParsedDocument(
        text=text,
        source_type="docx",
        parser="docx_zip_xml",
        metadata={"paragraph_count": len(paragraphs)},
    )


def parse_pdf_file(path: Path) -> ParsedDocument:
    try:
        fitz: Any = importlib.import_module("fitz")
    except ImportError as exc:
        raise UnsupportedDocumentFormatError(
            "PDF parsing requires PyMuPDF. Install it before parsing PDF files."
        ) from exc

    pages: list[str] = []
    with fitz.open(str(path)) as document:
        for page in document:
            pages.append(str(page.get_text("text")).strip())

    text = _normalize_text("\n\n".join(page for page in pages if page))
    _ensure_text(text)
    return ParsedDocument(
        text=text,
        source_type="pdf",
        parser="pymupdf",
        metadata={"page_count": len(pages)},
    )


def _document_suffix(path: Path, filename: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix
    return path.suffix.lower()


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip()


def _ensure_text(text: str) -> None:
    if not text.strip():
        raise DocumentParseError("Parsed document has no readable text.")


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text else 0


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + len("\n---\n") :].strip()


def _markdown_sections(text: str) -> list[dict[str, int | str]]:
    sections: list[dict[str, int | str]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        marks, _, title = stripped.partition(" ")
        if 1 <= len(marks) <= 6 and set(marks) == {"#"} and title.strip():
            sections.append({"level": len(marks), "title": title.strip(), "line": index})
    return sections
