from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class EmbeddingError(Exception):
    """Base exception for embedding failures."""


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when embedding settings are incomplete."""


class EmbeddingProviderError(EmbeddingError):
    """Raised when an embedding provider returns an error."""


class EmbeddingResponseError(EmbeddingError):
    """Raised when an embedding provider response is malformed."""


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str
    dimensions: int
    usage: dict[str, int] = field(default_factory=dict)


class EmbeddingClient(Protocol):
    provider: str
    model: str

    async def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Return embeddings for texts in the same order as the input."""


class OpenAICompatibleEmbeddingClient:
    provider: str
    model: str

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        expected_dimensions: int | None = None,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.expected_dimensions = expected_dimensions
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        clean_texts = list(texts)
        if not clean_texts:
            raise EmbeddingConfigurationError("At least one non-empty text is required.")
        if any(not text.strip() for text in clean_texts):
            raise EmbeddingConfigurationError("Embedding texts cannot be blank.")
        if not self.base_url:
            raise EmbeddingConfigurationError("Embedding base URL is required.")
        if not self.api_key:
            raise EmbeddingConfigurationError("Embedding API key is required.")
        if not self.model:
            raise EmbeddingConfigurationError("Embedding model is required.")

        payload = await self._post_embeddings(clean_texts)
        vectors = _extract_vectors(payload, expected_count=len(clean_texts))
        dimensions = len(vectors[0]) if vectors else 0
        if self.expected_dimensions is not None and dimensions != self.expected_dimensions:
            raise EmbeddingResponseError(
                f"Embedding dimensions mismatch: expected {self.expected_dimensions}, "
                f"got {dimensions}."
            )

        return EmbeddingBatch(
            vectors=vectors,
            model=str(payload.get("model") or self.model),
            dimensions=dimensions,
            usage=_extract_usage(payload.get("usage")),
        )

    async def _post_embeddings(self, texts: list[str]) -> dict[str, Any]:
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        request_json = {"model": self.model, "input": texts}
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.post(url, json=request_json, headers=headers)

        if response.status_code >= 400:
            raise EmbeddingProviderError(
                f"Embedding provider returned HTTP {response.status_code}: {response.text}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise EmbeddingResponseError("Embedding provider returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise EmbeddingResponseError("Embedding provider response must be a JSON object.")
        return data


def _extract_vectors(payload: dict[str, Any], *, expected_count: int) -> list[list[float]]:
    raw_data = payload.get("data")
    if not isinstance(raw_data, list) or len(raw_data) != expected_count:
        raise EmbeddingResponseError("Embedding provider returned unexpected data length.")

    indexed_items = []
    for fallback_index, item in enumerate(raw_data):
        if not isinstance(item, dict):
            raise EmbeddingResponseError("Embedding data item must be an object.")
        index = int(item.get("index", fallback_index))
        indexed_items.append((index, item))

    vectors: list[list[float]] = []
    for _, item in sorted(indexed_items, key=lambda pair: pair[0]):
        embedding = item.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingResponseError("Embedding data item is missing embedding vector.")
        try:
            vectors.append([float(value) for value in embedding])
        except (TypeError, ValueError) as exc:
            raise EmbeddingResponseError("Embedding vector must contain numbers.") from exc

    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise EmbeddingResponseError("Embedding vectors must have consistent dimensions.")
    return vectors


def _extract_usage(raw_usage: Any) -> dict[str, int]:
    if not isinstance(raw_usage, dict):
        return {}
    usage: dict[str, int] = {}
    for key, value in raw_usage.items():
        if isinstance(key, str) and isinstance(value, int):
            usage[key] = value
    return usage
