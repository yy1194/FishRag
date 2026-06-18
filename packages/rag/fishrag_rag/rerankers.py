from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from fishrag_rag.resilience import retry_async, should_retry_http_response
from fishrag_rag.retrieval import RetrievalHit


class RerankerError(Exception):
    """Base exception for reranker failures."""


class RerankerConfigurationError(RerankerError):
    """Raised when reranker settings are incomplete."""


class RerankerProviderError(RerankerError):
    """Raised when reranker provider returns an error."""


class RerankerResponseError(RerankerError):
    """Raised when reranker response cannot be parsed."""


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


class RerankerClient(Protocol):
    provider: str
    model: str

    async def rerank(
        self,
        *,
        query: str,
        hits: Sequence[RetrievalHit],
        top_n: int,
    ) -> list[RetrievalHit]:
        """Rerank retrieval hits."""


class OpenAICompatibleRerankerClient:
    provider: str
    model: str

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.transport = transport

    async def rerank(
        self,
        *,
        query: str,
        hits: Sequence[RetrievalHit],
        top_n: int,
    ) -> list[RetrievalHit]:
        if not hits:
            return []
        if not self.base_url:
            raise RerankerConfigurationError("Reranker base URL is required.")
        if not self.api_key:
            raise RerankerConfigurationError("Reranker API key is required.")
        if not self.model:
            raise RerankerConfigurationError("Reranker model is required.")

        payload = await self._post_rerank(
            query=query,
            documents=[hit.content for hit in hits],
            top_n=top_n,
        )
        results = _extract_rerank_results(payload)
        reranked: list[RetrievalHit] = []
        for result in results[:top_n]:
            if result.index < 0 or result.index >= len(hits):
                raise RerankerResponseError("Reranker result index is out of range.")
            hit = hits[result.index]
            metadata = dict(hit.metadata)
            metadata["reranker_score"] = result.score
            reranked.append(
                RetrievalHit(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    chunk_index=hit.chunk_index,
                    content=hit.content,
                    score=result.score,
                    source="reranker",
                    metadata=metadata,
                )
            )
        return reranked

    async def _post_rerank(self, *, query: str, documents: list[str], top_n: int) -> dict[str, Any]:
        async def request() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                return await client.post(
                    f"{self.base_url}/rerank",
                    json={
                        "model": self.model,
                        "query": query,
                        "documents": documents,
                        "top_n": top_n,
                        "return_documents": False,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )

        response = await retry_async(
            request,
            attempts=self.max_attempts,
            retry_exceptions=(httpx.TransportError,),
            should_retry_result=should_retry_http_response,
            delay_seconds=self.retry_backoff_seconds,
        )
        if response.status_code >= 400:
            raise RerankerProviderError(
                f"Reranker provider returned HTTP {response.status_code}: {response.text}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RerankerResponseError("Reranker provider returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise RerankerResponseError("Reranker response must be a JSON object.")
        return data


def _extract_rerank_results(payload: dict[str, Any]) -> list[RerankResult]:
    raw_results = payload.get("results") or payload.get("data")
    if not isinstance(raw_results, list):
        raise RerankerResponseError("Reranker response is missing results.")

    results: list[RerankResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        score = item.get("relevance_score", item.get("score"))
        if score is None:
            raise RerankerResponseError("Reranker result is missing score.")
        results.append(RerankResult(index=int(item.get("index", 0)), score=float(score)))
    return sorted(results, key=lambda result: result.score, reverse=True)
