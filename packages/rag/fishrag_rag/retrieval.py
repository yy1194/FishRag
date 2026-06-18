from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    score: float
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    id: str
    document_id: str
    chunk_id: str
    chunk_index: int
    content: str
    score: float
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RagSearchResult:
    query: str
    hits: list[RetrievalHit]
    citations: list[Citation]


@dataclass(frozen=True)
class RagAnswer:
    query: str
    answer: str
    citations: list[Citation]
    is_answered: bool


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[RetrievalHit]],
    *,
    k: int = 60,
    limit: int = 10,
) -> list[RetrievalHit]:
    """Fuse ranked retrieval lists using reciprocal rank fusion."""

    if limit <= 0:
        return []

    fusion_scores: dict[str, float] = {}
    best_hits: dict[str, RetrievalHit] = {}
    retrieval_sources: dict[str, set[str]] = {}
    source_scores: dict[str, dict[str, float]] = {}

    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            key = _hit_key(hit)
            fusion_scores[key] = fusion_scores.get(key, 0.0) + 1.0 / (k + rank)
            retrieval_sources.setdefault(key, set()).add(hit.source)
            _merge_source_score(source_scores.setdefault(key, {}), hit)
            if key not in best_hits or hit.score > best_hits[key].score:
                best_hits[key] = hit

    fused_hits: list[RetrievalHit] = []
    for key, fusion_score in sorted(
        fusion_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:limit]:
        hit = best_hits[key]
        metadata = dict(hit.metadata)
        metadata["fusion_score"] = fusion_score
        metadata["retrieval_sources"] = sorted(retrieval_sources.get(key, set()))
        metadata["source_scores"] = source_scores.get(key, {})
        fused_hits.append(
            RetrievalHit(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                chunk_index=hit.chunk_index,
                content=hit.content,
                score=fusion_score,
                source="hybrid",
                metadata=metadata,
            )
        )
    return fused_hits


def build_citations(hits: Sequence[RetrievalHit]) -> list[Citation]:
    return [
        Citation(
            id=f"C{index}",
            document_id=hit.document_id,
            chunk_id=hit.chunk_id,
            chunk_index=hit.chunk_index,
            content=hit.content,
            score=hit.score,
            source=hit.source,
            metadata=dict(hit.metadata),
        )
        for index, hit in enumerate(hits, start=1)
    ]


def rag_search(
    query: str,
    hits: Sequence[RetrievalHit],
    *,
    limit: int | None = None,
) -> RagSearchResult:
    selected_hits = list(hits if limit is None else hits[:limit])
    return RagSearchResult(
        query=query,
        hits=selected_hits,
        citations=build_citations(selected_hits),
    )


def no_evidence_answer(query: str) -> RagAnswer:
    return RagAnswer(
        query=query,
        answer=(
            "知识库中没有检索到足够证据来回答该问题。"
            "请补充相关资料或换一种更具体的问法；我不会基于未检索到的依据编造医学结论。"
        ),
        citations=[],
        is_answered=False,
    )


def _hit_key(hit: RetrievalHit) -> str:
    if hit.chunk_id:
        return hit.chunk_id
    return f"{hit.document_id}:{hit.chunk_index}"


def _merge_source_score(scores: dict[str, float], hit: RetrievalHit) -> None:
    scores[hit.source] = max(scores.get(hit.source, float("-inf")), hit.score)
