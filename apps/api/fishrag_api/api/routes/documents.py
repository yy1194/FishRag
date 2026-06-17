from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile, status
from fishrag_common.config import Settings, get_settings
from fishrag_rag.documents import DocumentStatus, validate_document_status_transition
from fishrag_rag.embeddings import EmbeddingClient, EmbeddingError
from fishrag_rag.keyword_index import (
    KeywordIndexClient,
    KeywordIndexDocument,
    KeywordIndexError,
)
from fishrag_rag.parsing import (
    DocumentParseError,
    ParsedDocument,
    UnsupportedDocumentFormatError,
    parse_document_file,
)
from fishrag_rag.processing import (
    DocumentProcessingError,
    build_chunked_document,
    estimate_token_count,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import get_embedding_client, get_keyword_index_client, get_session
from fishrag_api.core.errors import AppError
from fishrag_api.db.models import Document, new_id
from fishrag_api.db.models import DocumentChunk as DocumentChunkModel
from fishrag_api.services.documents import (
    EmptyUploadError,
    UploadStorageError,
    UploadTooLargeError,
    remove_stored_upload,
    resolve_stored_upload_path,
    save_upload_file,
)

router = APIRouter(prefix="/documents", tags=["documents"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbeddingClientDep = Annotated[EmbeddingClient, Depends(get_embedding_client)]
KeywordIndexClientDep = Annotated[KeywordIndexClient, Depends(get_keyword_index_client)]
DocumentStatusLiteral = Literal["uploaded", "processing", "indexed", "failed"]


class DocumentResponse(BaseModel):
    id: str
    filename: str
    content_type: str | None
    status: DocumentStatusLiteral
    checksum: str | None
    storage_path: str
    metadata: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None


class DocumentStatusUpdateRequest(BaseModel):
    status: DocumentStatusLiteral
    error_message: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class DocumentParseResponse(BaseModel):
    document_id: str
    status: DocumentStatusLiteral
    source_type: str
    parser: str
    text_preview: str
    text_length: int
    metadata: dict[str, Any]


class DocumentChunkingRequest(BaseModel):
    max_chars: int = Field(default=1200, ge=100, le=8000)
    overlap_chars: int = Field(default=150, ge=0, le=2000)

    model_config = ConfigDict(extra="forbid")


class DocumentChunkResponse(BaseModel):
    id: str
    chunk_index: int
    content_preview: str
    char_count: int
    token_count: int | None
    metadata: dict[str, Any]


class DocumentChunkingResponse(BaseModel):
    document_id: str
    status: DocumentStatusLiteral
    chunk_count: int
    section_count: int
    chunks: list[DocumentChunkResponse]


class DocumentEmbeddingRequest(BaseModel):
    batch_size: int = Field(default=16, ge=1, le=128)
    overwrite: bool = False

    model_config = ConfigDict(extra="forbid")


class DocumentEmbeddingResponse(BaseModel):
    document_id: str
    status: DocumentStatusLiteral
    provider: str
    model: str
    dimensions: int
    embedded_chunk_count: int
    skipped_chunk_count: int
    usage: dict[str, int]


class DocumentKeywordIndexRequest(BaseModel):
    refresh: bool = False

    model_config = ConfigDict(extra="forbid")


class DocumentKeywordIndexResponse(BaseModel):
    document_id: str
    status: DocumentStatusLiteral
    index_name: str
    indexed_chunk_count: int
    error_count: int
    errors: list[str]


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    session: DbSession,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str | None, Form()] = None,
) -> DocumentResponse:
    custom_metadata = _parse_metadata(metadata)
    document_id = new_id()

    try:
        stored = await save_upload_file(
            file,
            document_id=document_id,
            upload_dir=settings.upload_dir,
            max_bytes=settings.max_upload_bytes,
        )
    except EmptyUploadError as exc:
        raise AppError(str(exc), code="empty_upload", status_code=400) from exc
    except UploadTooLargeError as exc:
        raise AppError(str(exc), code="upload_too_large", status_code=413) from exc
    except UploadStorageError as exc:
        raise AppError(str(exc), code="upload_storage_error", status_code=400) from exc

    document = Document(
        id=document_id,
        owner_user_id=None,
        filename=stored.filename,
        content_type=file.content_type,
        status=DocumentStatus.UPLOADED.value,
        checksum=stored.checksum,
        storage_path=stored.storage_path,
        metadata_={
            "source": "upload",
            "size_bytes": stored.size_bytes,
            "original_filename": stored.original_filename,
            "custom": custom_metadata,
        },
    )

    try:
        session.add(document)
        await session.commit()
        await session.refresh(document)
    except Exception:
        remove_stored_upload(stored)
        raise

    return _to_response(document)


@router.post("/{document_id}/parse", response_model=DocumentParseResponse)
async def parse_document(
    document_id: str,
    session: DbSession,
    settings: SettingsDep,
    preview_chars: Annotated[int, Query(ge=0, le=20000)] = 2000,
) -> DocumentParseResponse:
    document = await session.get(Document, document_id)
    if document is None:
        raise AppError("Document not found.", code="document_not_found", status_code=404)

    path = resolve_stored_upload_path(settings.upload_dir, document.storage_path)
    parsed = await _parse_stored_document(session, document, path)

    previous_status = document.status
    try:
        target_status = validate_document_status_transition(
            previous_status,
            DocumentStatus.PROCESSING,
        )
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_document_status_transition") from exc

    metadata = dict(document.metadata_ or {})
    metadata["parse"] = {
        "source_type": parsed.source_type,
        "parser": parsed.parser,
        "text_length": parsed.text_length,
        "metadata": parsed.metadata,
    }
    metadata["status_history"] = _append_status_history(
        metadata,
        previous_status=previous_status,
        target_status=target_status.value,
    )
    document.status = target_status.value
    document.metadata_ = metadata
    await session.commit()
    await session.refresh(document)

    return DocumentParseResponse(
        document_id=document.id,
        status=_to_status_literal(document.status),
        source_type=parsed.source_type,
        parser=parsed.parser,
        text_preview=parsed.text[:preview_chars],
        text_length=parsed.text_length,
        metadata=parsed.metadata,
    )


@router.post("/{document_id}/chunks", response_model=DocumentChunkingResponse)
async def chunk_document(
    document_id: str,
    request: Annotated[DocumentChunkingRequest, Body()],
    session: DbSession,
    settings: SettingsDep,
) -> DocumentChunkingResponse:
    if request.overlap_chars >= request.max_chars:
        raise AppError(
            "overlap_chars must be smaller than max_chars.",
            code="invalid_chunk_options",
        )

    document = await session.get(Document, document_id)
    if document is None:
        raise AppError("Document not found.", code="document_not_found", status_code=404)

    path = resolve_stored_upload_path(settings.upload_dir, document.storage_path)
    parsed = await _parse_stored_document(session, document, path)

    try:
        chunked = build_chunked_document(
            parsed,
            max_chars=request.max_chars,
            overlap_chars=request.overlap_chars,
        )
    except DocumentProcessingError as exc:
        await _mark_document_failed(session, document, str(exc))
        raise AppError(str(exc), code="document_processing_error") from exc

    previous_status = document.status
    try:
        target_status = validate_document_status_transition(
            previous_status,
            DocumentStatus.PROCESSING,
        )
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_document_status_transition") from exc

    await session.execute(
        delete(DocumentChunkModel).where(DocumentChunkModel.document_id == document.id)
    )
    db_chunks: list[DocumentChunkModel] = []
    for chunk in chunked.chunks:
        metadata = dict(chunk.metadata)
        token_count = int(metadata.get("token_count", estimate_token_count(chunk.text)))
        db_chunk = DocumentChunkModel(
            id=new_id(),
            document_id=document.id,
            chunk_index=chunk.index,
            content=chunk.text,
            embedding=None,
            token_count=token_count,
            metadata_=metadata,
        )
        session.add(db_chunk)
        db_chunks.append(db_chunk)

    metadata = dict(document.metadata_ or {})
    metadata["parse"] = {
        "source_type": parsed.source_type,
        "parser": parsed.parser,
        "text_length": parsed.text_length,
        "metadata": parsed.metadata,
    }
    metadata["chunking"] = {
        **chunked.metadata,
        "sections": [
            {
                "index": section.index,
                "title": section.title,
                "level": section.level,
                "start": section.start,
                "end": section.end,
                "path": list(section.path),
            }
            for section in chunked.sections
        ],
    }
    metadata["status_history"] = _append_status_history(
        metadata,
        previous_status=previous_status,
        target_status=target_status.value,
    )
    document.status = target_status.value
    document.metadata_ = metadata
    await session.commit()
    await session.refresh(document)

    return DocumentChunkingResponse(
        document_id=document.id,
        status=_to_status_literal(document.status),
        chunk_count=len(db_chunks),
        section_count=len(chunked.sections),
        chunks=[_to_chunk_response(chunk) for chunk in db_chunks],
    )


@router.post("/{document_id}/embeddings", response_model=DocumentEmbeddingResponse)
async def embed_document_chunks(
    document_id: str,
    request: Annotated[DocumentEmbeddingRequest, Body()],
    session: DbSession,
    settings: SettingsDep,
    embedding_client: EmbeddingClientDep,
) -> DocumentEmbeddingResponse:
    document = await session.get(Document, document_id)
    if document is None:
        raise AppError("Document not found.", code="document_not_found", status_code=404)

    chunks = await _load_document_chunks(session, document.id)
    if not chunks:
        raise AppError("Document has no chunks to embed.", code="document_has_no_chunks")

    target_chunks = [chunk for chunk in chunks if request.overwrite or chunk.embedding is None]
    if not target_chunks:
        return _embedding_response(
            document=document,
            settings=settings,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            embedded_count=0,
            skipped_count=len(chunks),
            usage={},
        )

    usage: dict[str, int] = {}
    embedded_count = 0
    model = settings.embedding_model
    dimensions = settings.embedding_dimensions
    try:
        for batch in _batched(target_chunks, request.batch_size):
            result = await embedding_client.embed_texts([chunk.content for chunk in batch])
            model = result.model
            dimensions = result.dimensions
            _merge_usage(usage, result.usage)
            for chunk, vector in zip(batch, result.vectors, strict=True):
                chunk.embedding = vector
                metadata = dict(chunk.metadata_ or {})
                metadata["embedding"] = {
                    "provider": settings.embedding_provider,
                    "model": result.model,
                    "dimensions": result.dimensions,
                }
                chunk.metadata_ = metadata
                embedded_count += 1
    except EmbeddingError as exc:
        raise AppError(str(exc), code="embedding_error", status_code=502) from exc

    metadata = dict(document.metadata_ or {})
    metadata["embedding"] = {
        "provider": settings.embedding_provider,
        "model": model,
        "dimensions": dimensions,
        "embedded_chunk_count": embedded_count,
        "total_chunk_count": len(chunks),
    }
    document.metadata_ = metadata
    await session.commit()
    await session.refresh(document)

    return _embedding_response(
        document=document,
        settings=settings,
        model=model,
        dimensions=dimensions,
        embedded_count=embedded_count,
        skipped_count=len(chunks) - embedded_count,
        usage=usage,
    )


@router.post("/{document_id}/keyword-index", response_model=DocumentKeywordIndexResponse)
async def index_document_keywords(
    document_id: str,
    request: Annotated[DocumentKeywordIndexRequest, Body()],
    session: DbSession,
    keyword_index_client: KeywordIndexClientDep,
) -> DocumentKeywordIndexResponse:
    document = await session.get(Document, document_id)
    if document is None:
        raise AppError("Document not found.", code="document_not_found", status_code=404)

    chunks = await _load_document_chunks(session, document.id)
    if not chunks:
        raise AppError("Document has no chunks to index.", code="document_has_no_chunks")

    index_documents = [
        _to_keyword_index_document(document=document, chunk=chunk) for chunk in chunks
    ]
    try:
        await keyword_index_client.ensure_index()
        result = await keyword_index_client.bulk_index_documents(
            index_documents,
            refresh=request.refresh,
        )
    except KeywordIndexError as exc:
        raise AppError(str(exc), code="keyword_index_error", status_code=502) from exc

    if result.errors:
        return DocumentKeywordIndexResponse(
            document_id=document.id,
            status=_to_status_literal(document.status),
            index_name=result.index_name,
            indexed_chunk_count=result.indexed_count,
            error_count=len(result.errors),
            errors=result.errors,
        )

    previous_status = document.status
    try:
        target_status = validate_document_status_transition(
            previous_status,
            DocumentStatus.INDEXED,
        )
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_document_status_transition") from exc

    metadata = dict(document.metadata_ or {})
    metadata["keyword_index"] = {
        "index_name": result.index_name,
        "indexed_chunk_count": result.indexed_count,
    }
    metadata["status_history"] = _append_status_history(
        metadata,
        previous_status=previous_status,
        target_status=target_status.value,
    )
    document.status = target_status.value
    document.metadata_ = metadata
    await session.commit()
    await session.refresh(document)

    return DocumentKeywordIndexResponse(
        document_id=document.id,
        status=_to_status_literal(document.status),
        index_name=result.index_name,
        indexed_chunk_count=result.indexed_count,
        error_count=0,
        errors=[],
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, session: DbSession) -> DocumentResponse:
    document = await session.get(Document, document_id)
    if document is None:
        raise AppError("Document not found.", code="document_not_found", status_code=404)
    return _to_response(document)


@router.patch("/{document_id}/status", response_model=DocumentResponse)
async def update_document_status(
    document_id: str,
    request: DocumentStatusUpdateRequest,
    session: DbSession,
) -> DocumentResponse:
    document = await session.get(Document, document_id)
    if document is None:
        raise AppError("Document not found.", code="document_not_found", status_code=404)

    try:
        target_status = validate_document_status_transition(document.status, request.status)
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_document_status_transition") from exc

    metadata = dict(document.metadata_ or {})
    metadata["status_history"] = _append_status_history(
        metadata,
        previous_status=document.status,
        target_status=target_status.value,
    )
    if target_status == DocumentStatus.FAILED and request.error_message:
        metadata["error_message"] = request.error_message

    document.status = target_status.value
    document.metadata_ = metadata
    await session.commit()
    await session.refresh(document)
    return _to_response(document)


def _parse_metadata(metadata: str | None) -> dict[str, Any]:
    if metadata is None or metadata.strip() == "":
        return {}

    try:
        parsed = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise AppError("Metadata must be valid JSON.", code="invalid_metadata") from exc

    if not isinstance(parsed, dict):
        raise AppError("Metadata must be a JSON object.", code="invalid_metadata")
    return parsed


def _to_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        status=_to_status_literal(document.status),
        checksum=document.checksum,
        storage_path=document.storage_path,
        metadata=dict(document.metadata_ or {}),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


async def _parse_stored_document(
    session: AsyncSession,
    document: Document,
    path: Path,
) -> ParsedDocument:
    if not path.exists():
        await _mark_document_failed(session, document, "Stored file was not found.")
        raise AppError(
            "Stored file was not found.",
            code="document_file_not_found",
            status_code=404,
        )

    try:
        return parse_document_file(
            path,
            content_type=document.content_type,
            filename=document.filename,
        )
    except UnsupportedDocumentFormatError as exc:
        await _mark_document_failed(session, document, str(exc))
        raise AppError(str(exc), code="unsupported_document_format", status_code=415) from exc
    except DocumentParseError as exc:
        await _mark_document_failed(session, document, str(exc))
        raise AppError(str(exc), code="document_parse_error") from exc


def _to_chunk_response(chunk: DocumentChunkModel) -> DocumentChunkResponse:
    return DocumentChunkResponse(
        id=chunk.id,
        chunk_index=chunk.chunk_index,
        content_preview=chunk.content[:500],
        char_count=len(chunk.content),
        token_count=chunk.token_count,
        metadata=dict(chunk.metadata_ or {}),
    )


def _to_keyword_index_document(
    *,
    document: Document,
    chunk: DocumentChunkModel,
) -> KeywordIndexDocument:
    metadata = dict(chunk.metadata_ or {})
    metadata.update(
        {
            "filename": document.filename,
            "content_type": document.content_type,
            "checksum": document.checksum,
            "storage_path": document.storage_path,
            "token_count": chunk.token_count,
        }
    )
    return KeywordIndexDocument(
        id=f"{document.id}:{chunk.id}",
        document_id=document.id,
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        metadata=metadata,
    )


async def _load_document_chunks(
    session: AsyncSession,
    document_id: str,
) -> list[DocumentChunkModel]:
    result = await session.execute(
        select(DocumentChunkModel)
        .where(DocumentChunkModel.document_id == document_id)
        .order_by(DocumentChunkModel.chunk_index)
    )
    return list(result.scalars().all())


def _embedding_response(
    *,
    document: Document,
    settings: Settings,
    model: str,
    dimensions: int,
    embedded_count: int,
    skipped_count: int,
    usage: dict[str, int],
) -> DocumentEmbeddingResponse:
    return DocumentEmbeddingResponse(
        document_id=document.id,
        status=_to_status_literal(document.status),
        provider=settings.embedding_provider,
        model=model,
        dimensions=dimensions,
        embedded_chunk_count=embedded_count,
        skipped_chunk_count=skipped_count,
        usage=usage,
    )


def _batched(items: list[DocumentChunkModel], size: int) -> list[list[DocumentChunkModel]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _merge_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for key, value in usage.items():
        total[key] = total.get(key, 0) + value


async def _mark_document_failed(
    session: AsyncSession,
    document: Document,
    error_message: str,
) -> None:
    previous_status = document.status
    try:
        target_status = validate_document_status_transition(previous_status, DocumentStatus.FAILED)
    except ValueError:
        target_status = DocumentStatus.FAILED

    metadata = dict(document.metadata_ or {})
    metadata["error_message"] = error_message
    metadata["status_history"] = _append_status_history(
        metadata,
        previous_status=previous_status,
        target_status=target_status.value,
    )
    document.status = target_status.value
    document.metadata_ = metadata
    await session.commit()
    await session.refresh(document)


def _append_status_history(
    metadata: dict[str, Any],
    *,
    previous_status: str,
    target_status: str,
) -> list[dict[str, str]]:
    history = list(metadata.get("status_history", []))
    if previous_status != target_status:
        history.append({"from": previous_status, "to": target_status})
    return history


def _to_status_literal(status_value: str) -> DocumentStatusLiteral:
    status = DocumentStatus(status_value)
    if status == DocumentStatus.UPLOADED:
        return "uploaded"
    if status == DocumentStatus.PROCESSING:
        return "processing"
    if status == DocumentStatus.INDEXED:
        return "indexed"
    return "failed"
