from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


_ALLOWED_STATUS_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.UPLOADED: frozenset({DocumentStatus.PROCESSING, DocumentStatus.FAILED}),
    DocumentStatus.PROCESSING: frozenset({DocumentStatus.INDEXED, DocumentStatus.FAILED}),
    DocumentStatus.INDEXED: frozenset({DocumentStatus.PROCESSING}),
    DocumentStatus.FAILED: frozenset({DocumentStatus.PROCESSING}),
}


def parse_document_status(status: str | DocumentStatus) -> DocumentStatus:
    if isinstance(status, DocumentStatus):
        return status
    try:
        return DocumentStatus(status)
    except ValueError as exc:
        raise ValueError(f"Unknown document status: {status}") from exc


def can_transition_document_status(
    current: str | DocumentStatus,
    target: str | DocumentStatus,
) -> bool:
    current_status = parse_document_status(current)
    target_status = parse_document_status(target)
    return target_status == current_status or target_status in _ALLOWED_STATUS_TRANSITIONS[
        current_status
    ]


def validate_document_status_transition(
    current: str | DocumentStatus,
    target: str | DocumentStatus,
) -> DocumentStatus:
    target_status = parse_document_status(target)
    if not can_transition_document_status(current, target_status):
        current_status = parse_document_status(current)
        raise ValueError(
            f"Cannot transition document status from {current_status.value} "
            f"to {target_status.value}."
        )
    return target_status


def sanitize_document_filename(filename: str | None) -> str:
    raw_name = (filename or "").replace("\\", "/").split("/")[-1]
    normalized = unicodedata.normalize("NFKC", raw_name)
    safe_name = re.sub(r"[^\w.\-]+", "_", normalized, flags=re.UNICODE)
    safe_name = safe_name.strip("._ ")
    if not safe_name:
        return "upload.bin"
    if len(safe_name) <= 180:
        return safe_name

    stem, dot, suffix = safe_name.rpartition(".")
    if dot and len(suffix) <= 24:
        return f"{stem[:155]}.{suffix}"
    return safe_name[:180]


def build_document_storage_path(
    document_id: str,
    filename: str,
    *,
    uploaded_at: datetime | None = None,
) -> str:
    safe_document_id = re.sub(r"[^A-Za-z0-9_-]+", "_", document_id).strip("_")
    if not safe_document_id:
        raise ValueError("Document id cannot be empty.")

    timestamp = uploaded_at or datetime.now(tz=UTC)
    safe_filename = sanitize_document_filename(filename)
    return PurePosixPath(
        f"{timestamp:%Y}",
        f"{timestamp:%m}",
        f"{timestamp:%d}",
        safe_document_id,
        safe_filename,
    ).as_posix()
