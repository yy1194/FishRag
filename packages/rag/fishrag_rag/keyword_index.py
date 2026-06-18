from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from fishrag_rag.resilience import retry_async, should_retry_http_response


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


@dataclass(frozen=True)
class KeywordSearchHit:
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


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

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[KeywordSearchHit]:
        """Search the keyword index."""


class OpenSearchKeywordIndexClient:
    index_name: str

    def __init__(
        self,
        *,
        base_url: str,
        index_name: str,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.index_name = index_name.strip()
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.transport = transport

    async def ensure_index(self) -> None:
        self._validate_settings()
        async with self._client() as client:
            exists_response = await self._request(client, "HEAD", f"/{self.index_name}")
            if exists_response.status_code == 200:
                return
            if exists_response.status_code != 404:
                raise KeywordIndexProviderError(
                    f"OpenSearch index check failed with HTTP {exists_response.status_code}."
                )

            create_response = await self._request(
                client,
                "PUT",
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
            response = await self._request(
                client,
                "POST",
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

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[KeywordSearchHit]:
        self._validate_settings()
        if not query.strip():
            return []

        payload = {
            "size": limit,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": [
                        "content^4",
                        "metadata.section_title^2",
                        "metadata.section_path",
                    ],
                }
            },
        }
        async with self._client() as client:
            response = await self._request(
                client,
                "POST",
                f"/{self.index_name}/_search",
                json=payload,
            )

        if response.status_code >= 400:
            raise KeywordIndexProviderError(
                f"OpenSearch search failed with HTTP {response.status_code}: {response.text}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise KeywordIndexResponseError("OpenSearch search response was not JSON.") from exc
        if not isinstance(data, dict):
            raise KeywordIndexResponseError("OpenSearch search response must be a JSON object.")
        return _search_hits(data)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        async def request() -> httpx.Response:
            return await client.request(method, url, **kwargs)

        return await retry_async(
            request,
            attempts=self.max_attempts,
            retry_exceptions=(httpx.TransportError,),
            should_retry_result=should_retry_http_response,
            delay_seconds=self.retry_backoff_seconds,
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


def _search_hits(payload: dict[str, Any]) -> list[KeywordSearchHit]:
    raw_hits = payload.get("hits")
    if not isinstance(raw_hits, dict):
        raise KeywordIndexResponseError("OpenSearch search response is missing hits.")
    items = raw_hits.get("hits")
    if not isinstance(items, list):
        raise KeywordIndexResponseError("OpenSearch search hits must be a list.")

    hits: list[KeywordSearchHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("_source")
        if not isinstance(source, dict):
            continue
        hits.append(
            KeywordSearchHit(
                chunk_id=str(source.get("chunk_id") or item.get("_id")),
                document_id=str(source.get("document_id")),
                chunk_index=int(source.get("chunk_index", 0)),
                content=str(source.get("content", "")),
                score=float(item.get("_score", 0.0)),
                metadata=dict(source.get("metadata") or {}),
            )
        )
    return hits


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
