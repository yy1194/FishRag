from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class KeywordIndexError(Exception):
    """Base exception for keyword index failures."""


class KeywordIndexConfigurationError(KeywordIndexError):
    """Raised when keyword index settings are incomplete."""


class KeywordIndexProviderError(KeywordIndexError):
    """Raised when OpenSearch returns an error."""


class KeywordIndexResponseError(KeywordIndexError):
    """Raised when OpenSearch returns an unexpected response."""


@dataclass(frozen=True)
class KeywordIndexDocument:
    id: str
    document_id: str
    chunk_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_source(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class KeywordIndexBatchResult:
    index_name: str
    indexed_count: int
    errors: list[str] = field(default_factory=list)


class KeywordIndexClient(Protocol):
    index_name: str

    async def ensure_index(self) -> None:
        """Create the keyword index if it does not exist."""

    async def bulk_index_documents(
        self,
        documents: Sequence[KeywordIndexDocument],
        *,
        refresh: bool = False,
    ) -> KeywordIndexBatchResult:
        """Index documents using the OpenSearch bulk API."""


class OpenSearchKeywordIndexClient:
    index_name: str

    def __init__(
        self,
        *,
        base_url: str,
        index_name: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.index_name = index_name.strip()
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def ensure_index(self) -> None:
        self._validate_settings()
        async with self._client() as client:
            exists_response = await client.head(f"/{self.index_name}")
            if exists_response.status_code == 200:
                return
            if exists_response.status_code != 404:
                raise KeywordIndexProviderError(
                    f"OpenSearch index check failed with HTTP {exists_response.status_code}."
                )

            create_response = await client.put(
                f"/{self.index_name}",
                json=_index_mapping(),
            )
            if create_response.status_code >= 400:
                raise KeywordIndexProviderError(
                    "OpenSearch index creation failed with HTTP "
                    f"{create_response.status_code}: {create_response.text}"
                )

    async def bulk_index_documents(
        self,
        documents: Sequence[KeywordIndexDocument],
        *,
        refresh: bool = False,
    ) -> KeywordIndexBatchResult:
        self._validate_settings()
        if not documents:
            return KeywordIndexBatchResult(index_name=self.index_name, indexed_count=0)

        body = _bulk_body(self.index_name, documents)
        async with self._client() as client:
            response = await client.post(
                f"/_bulk?refresh={str(refresh).lower()}",
                content=body,
                headers={"Content-Type": "application/x-ndjson"},
            )

        if response.status_code >= 400:
            raise KeywordIndexProviderError(
                f"OpenSearch bulk index failed with HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise KeywordIndexResponseError("OpenSearch bulk response was not JSON.") from exc
        if not isinstance(payload, dict):
            raise KeywordIndexResponseError("OpenSearch bulk response must be a JSON object.")

        errors = _bulk_errors(payload)
        return KeywordIndexBatchResult(
            index_name=self.index_name,
            indexed_count=len(documents) - len(errors),
            errors=errors,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        )

    def _validate_settings(self) -> None:
        if not self.base_url:
            raise KeywordIndexConfigurationError("OpenSearch base URL is required.")
        if not self.index_name:
            raise KeywordIndexConfigurationError("OpenSearch index name is required.")


def _bulk_body(index_name: str, documents: Sequence[KeywordIndexDocument]) -> bytes:
    lines: list[str] = []
    for document in documents:
        lines.append(json.dumps({"index": {"_index": index_name, "_id": document.id}}))
        lines.append(json.dumps(document.as_source(), ensure_ascii=False))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _bulk_errors(payload: dict[str, Any]) -> list[str]:
    if not payload.get("errors"):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        raise KeywordIndexResponseError("OpenSearch bulk response items must be a list.")

    errors: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        action = item.get("index")
        if not isinstance(action, dict):
            continue
        error = action.get("error")
        if error:
            errors.append(json.dumps(error, ensure_ascii=False))
    return errors


def _index_mapping() -> dict[str, Any]:
    return {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            }
        },
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "content": {"type": "text"},
                "metadata": {
                    "properties": {
                        "filename": {"type": "keyword"},
                        "content_type": {"type": "keyword"},
                        "section_title": {"type": "text"},
                        "section_path": {"type": "keyword"},
                        "source_type": {"type": "keyword"},
                        "parser": {"type": "keyword"},
                    }
                },
            }
        },
    }
