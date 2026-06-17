from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fishrag_common.config import Settings, get_settings
from fishrag_rag.documents import DocumentStatus, validate_document_status_transition
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import get_session
from fishrag_api.core.errors import AppError
from fishrag_api.db.models import Document, new_id
from fishrag_api.services.documents import (
    EmptyUploadError,
    UploadStorageError,
    UploadTooLargeError,
    remove_stored_upload,
    save_upload_file,
)

router = APIRouter(prefix="/documents", tags=["documents"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
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
    metadata["status_history"] = [
        *metadata.get("status_history", []),
        {"from": document.status, "to": target_status.value},
    ]
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


def _to_status_literal(status_value: str) -> DocumentStatusLiteral:
    status = DocumentStatus(status_value)
    if status == DocumentStatus.UPLOADED:
        return "uploaded"
    if status == DocumentStatus.PROCESSING:
        return "processing"
    if status == DocumentStatus.INDEXED:
        return "indexed"
    return "failed"
