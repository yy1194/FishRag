from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from fishrag_rag.documents import build_document_storage_path, sanitize_document_filename

CHUNK_SIZE = 1024 * 1024


class UploadStorageError(Exception):
    """Base class for upload storage errors."""


class EmptyUploadError(UploadStorageError):
    """Raised when an uploaded file has no bytes."""


class UploadTooLargeError(UploadStorageError):
    """Raised when an uploaded file exceeds the configured size limit."""


@dataclass(frozen=True)
class StoredUpload:
    original_filename: str
    filename: str
    storage_path: str
    absolute_path: Path
    checksum: str
    size_bytes: int


async def save_upload_file(
    file: UploadFile,
    *,
    document_id: str,
    upload_dir: Path,
    max_bytes: int,
) -> StoredUpload:
    original_filename = file.filename or "upload.bin"
    filename = sanitize_document_filename(original_filename)
    storage_path = build_document_storage_path(document_id, filename)
    absolute_path = _resolve_upload_path(upload_dir, storage_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)

    checksum = hashlib.sha256()
    size_bytes = 0

    try:
        with absolute_path.open("wb") as output:
            while chunk := await file.read(CHUNK_SIZE):
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise UploadTooLargeError(
                        f"Uploaded file exceeds the configured limit of {max_bytes} bytes."
                    )
                checksum.update(chunk)
                output.write(chunk)
    except UploadStorageError:
        absolute_path.unlink(missing_ok=True)
        raise

    if size_bytes == 0:
        absolute_path.unlink(missing_ok=True)
        raise EmptyUploadError("Uploaded file is empty.")

    return StoredUpload(
        original_filename=original_filename,
        filename=filename,
        storage_path=storage_path,
        absolute_path=absolute_path,
        checksum=checksum.hexdigest(),
        size_bytes=size_bytes,
    )


def remove_stored_upload(upload: StoredUpload) -> None:
    upload.absolute_path.unlink(missing_ok=True)


def resolve_stored_upload_path(upload_dir: Path, storage_path: str) -> Path:
    return _resolve_upload_path(upload_dir, storage_path)


def _resolve_upload_path(upload_dir: Path, storage_path: str) -> Path:
    base_dir = upload_dir.resolve()
    target_path = (base_dir / Path(storage_path)).resolve()
    if not target_path.is_relative_to(base_dir):
        raise UploadStorageError("Resolved upload path escapes the upload directory.")
    return target_path
