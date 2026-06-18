from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Depends
from fishrag_agent.approval import apply_medical_safety_guard
from fishrag_common.config import Settings, get_settings
from fishrag_rag.embeddings import EmbeddingClient, EmbeddingError
from fishrag_rag.generation import ChatClient, ChatGenerationError, generate_rag_answer
from fishrag_rag.keyword_index import KeywordIndexClient, KeywordIndexError, KeywordSearchHit
from fishrag_rag.rerankers import RerankerClient, RerankerError
from fishrag_rag.retrieval import (
    Citation,
    RagAnswer,
    RagSearchResult,
    RetrievalHit,
    rag_search,
    reciprocal_rank_fusion,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import (
    get_chat_client,
    get_embedding_client,
    get_keyword_index_client,
    get_reranker_client,
    get_session,
)
from fishrag_api.core.errors import AppError

router = APIRouter(prefix="/rag", tags=["rag"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbeddingClientDep = Annotated[EmbeddingClient, Depends(get_embedding_client)]
KeywordIndexClientDep = Annotated[KeywordIndexClient, Depends(get_keyword_index_client)]
RerankerClientDep = Annotated[RerankerClient, Depends(get_reranker_client)]
ChatClientDep = Annotated[ChatClient, Depends(get_chat_client)]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=10, ge=1, le=100)

    model_config = ConfigDict(extra="forbid")


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    vector_limit: int = Field(default=20, ge=1, le=100)
    keyword_limit: int = Field(default=20, ge=1, le=100)
    limit: int = Field(default=10, ge=1, le=50)
    use_reranker: bool = True
    reranker_top_n: int = Field(default=10, ge=1, le=50)

    model_config = ConfigDict(extra="forbid")


class RagAnswerRequest(RagSearchRequest):
    pass


class RetrievalHitResponse(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    score: float
    source: str
    metadata: dict[str, Any]


class CitationResponse(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    chunk_index: int
    content: str
    score: float
    source: str
    metadata: dict[str, Any]


class RagSearchResponse(BaseModel):
    query: str
    hits: list[RetrievalHitResponse]
    citations: list[CitationResponse]


class RagAnswerResponse(BaseModel):
    query: str
    answer: str
    citations: list[CitationResponse]
    is_answered: bool
    safety: dict[str, Any] = Field(default_factory=dict)


@router.post("/vector-search", response_model=RagSearchResponse)
async def vector_search(
    request: Annotated[SearchRequest, Body()],
    session: DbSession,
    settings: SettingsDep,
    embedding_client: EmbeddingClientDep,
) -> RagSearchResponse:
    hits = await _vector_search(
        query=request.query,
        limit=request.limit,
        session=session,
        settings=settings,
        embedding_client=embedding_client,
    )
    return _to_search_response(rag_search(request.query, hits))


@router.post("/keyword-search", response_model=RagSearchResponse)
async def keyword_search(
    request: Annotated[SearchRequest, Body()],
    keyword_index_client: KeywordIndexClientDep,
) -> RagSearchResponse:
    hits = await _keyword_search(
        query=request.query,
        limit=request.limit,
        keyword_index_client=keyword_index_client,
    )
    return _to_search_response(rag_search(request.query, hits))


@router.post("/hybrid-search", response_model=RagSearchResponse)
async def hybrid_search(
    request: Annotated[RagSearchRequest, Body()],
    session: DbSession,
    settings: SettingsDep,
    embedding_client: EmbeddingClientDep,
    keyword_index_client: KeywordIndexClientDep,
    reranker_client: RerankerClientDep,
) -> RagSearchResponse:
    result = await _run_hybrid_search(
        request=request,
        session=session,
        settings=settings,
        embedding_client=embedding_client,
        keyword_index_client=keyword_index_client,
        reranker_client=reranker_client,
    )
    return _to_search_response(result)


@router.post("/search", response_model=RagSearchResponse)
async def search_rag(
    request: Annotated[RagSearchRequest, Body()],
    session: DbSession,
    settings: SettingsDep,
    embedding_client: EmbeddingClientDep,
    keyword_index_client: KeywordIndexClientDep,
    reranker_client: RerankerClientDep,
) -> RagSearchResponse:
    result = await _run_hybrid_search(
        request=request,
        session=session,
        settings=settings,
        embedding_client=embedding_client,
        keyword_index_client=keyword_index_client,
        reranker_client=reranker_client,
    )
    return _to_search_response(result)


@router.post("/answer", response_model=RagAnswerResponse)
async def answer_rag(
    request: Annotated[RagAnswerRequest, Body()],
    session: DbSession,
    settings: SettingsDep,
    embedding_client: EmbeddingClientDep,
    keyword_index_client: KeywordIndexClientDep,
    reranker_client: RerankerClientDep,
    chat_client: ChatClientDep,
) -> RagAnswerResponse:
    search_result = await _run_hybrid_search(
        request=request,
        session=session,
        settings=settings,
        embedding_client=embedding_client,
        keyword_index_client=keyword_index_client,
        reranker_client=reranker_client,
    )
    try:
        answer = await generate_rag_answer(
            query=request.query,
            hits=search_result.hits,
            citations=search_result.citations,
            chat_client=chat_client,
        )
    except ChatGenerationError as exc:
        raise AppError(str(exc), code="chat_generation_error", status_code=502) from exc
    guarded = apply_medical_safety_guard(
        query=request.query,
        answer=answer.answer,
        citation_count=len(answer.citations),
    )
    return _to_answer_response(
        RagAnswer(
            query=answer.query,
            answer=guarded.answer,
            citations=answer.citations,
            is_answered=answer.is_answered and guarded.is_answered,
        ),
        safety=guarded.assessment.as_dict(),
    )


async def _run_hybrid_search(
    *,
    request: RagSearchRequest,
    session: AsyncSession,
    settings: Settings,
    embedding_client: EmbeddingClient,
    keyword_index_client: KeywordIndexClient,
    reranker_client: RerankerClient,
) -> RagSearchResult:
    vector_hits = await _vector_search(
        query=request.query,
        limit=request.vector_limit,
        session=session,
        settings=settings,
        embedding_client=embedding_client,
    )
    keyword_hits = await _keyword_search(
        query=request.query,
        limit=request.keyword_limit,
        keyword_index_client=keyword_index_client,
    )
    fusion_limit = max(request.limit, request.reranker_top_n)
    fused_hits = reciprocal_rank_fusion(
        [vector_hits, keyword_hits],
        limit=fusion_limit,
    )

    selected_hits = fused_hits[: request.limit]
    if request.use_reranker and fused_hits:
        reranker_top_n = min(request.reranker_top_n, len(fused_hits))
        try:
            selected_hits = await reranker_client.rerank(
                query=request.query,
                hits=fused_hits,
                top_n=reranker_top_n,
            )
        except RerankerError as exc:
            raise AppError(str(exc), code="reranker_error", status_code=502) from exc
        selected_hits = selected_hits[: request.limit]

    return rag_search(request.query, selected_hits)


async def _vector_search(
    *,
    query: str,
    limit: int,
    session: AsyncSession,
    settings: Settings,
    embedding_client: EmbeddingClient,
) -> list[RetrievalHit]:
    try:
        embedding = await embedding_client.embed_texts([query])
    except EmbeddingError as exc:
        raise AppError(str(exc), code="embedding_error", status_code=502) from exc

    vector = embedding.vectors[0]
    if settings.embedding_dimensions and len(vector) != settings.embedding_dimensions:
        raise AppError(
            "Query embedding dimensions do not match configured dimensions.",
            code="embedding_dimension_mismatch",
            status_code=502,
        )

    result = await session.execute(
        text(
            """
            SELECT
              dc.id AS chunk_id,
              dc.document_id AS document_id,
              dc.chunk_index AS chunk_index,
              dc.content AS content,
              dc.metadata AS chunk_metadata,
              d.filename AS filename,
              d.content_type AS content_type,
              d.storage_path AS storage_path,
              1 - (dc.embedding <=> CAST(:query_vector AS vector)) AS score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """
        ),
        {"query_vector": _pgvector_literal(vector), "limit": limit},
    )
    rows = cast(Sequence[Mapping[str, Any]], result.mappings().all())
    return [_row_to_retrieval_hit(row, source="vector") for row in rows]


async def _keyword_search(
    *,
    query: str,
    limit: int,
    keyword_index_client: KeywordIndexClient,
) -> list[RetrievalHit]:
    try:
        hits = await keyword_index_client.search(query, limit=limit)
    except KeywordIndexError as exc:
        raise AppError(str(exc), code="keyword_index_error", status_code=502) from exc
    return [_keyword_hit_to_retrieval_hit(hit) for hit in hits]


def _row_to_retrieval_hit(row: Mapping[str, Any], *, source: str) -> RetrievalHit:
    metadata = _metadata_dict(row.get("chunk_metadata"))
    _add_if_present(metadata, "filename", row.get("filename"))
    _add_if_present(metadata, "content_type", row.get("content_type"))
    _add_if_present(metadata, "storage_path", row.get("storage_path"))
    return RetrievalHit(
        chunk_id=_string_value(row.get("chunk_id")),
        document_id=_string_value(row.get("document_id")),
        chunk_index=_int_value(row.get("chunk_index")),
        content=_string_value(row.get("content")),
        score=_float_value(row.get("score")),
        source=source,
        metadata=metadata,
    )


def _keyword_hit_to_retrieval_hit(hit: KeywordSearchHit) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        chunk_index=hit.chunk_index,
        content=hit.content,
        score=hit.score,
        source="keyword",
        metadata=dict(hit.metadata),
    )


def _to_search_response(result: RagSearchResult) -> RagSearchResponse:
    return RagSearchResponse(
        query=result.query,
        hits=[_to_hit_response(hit) for hit in result.hits],
        citations=[_to_citation_response(citation) for citation in result.citations],
    )


def _to_answer_response(
    answer: RagAnswer,
    *,
    safety: dict[str, Any] | None = None,
) -> RagAnswerResponse:
    return RagAnswerResponse(
        query=answer.query,
        answer=answer.answer,
        citations=[_to_citation_response(citation) for citation in answer.citations],
        is_answered=answer.is_answered,
        safety=safety or {},
    )


def _to_hit_response(hit: RetrievalHit) -> RetrievalHitResponse:
    return RetrievalHitResponse(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        chunk_index=hit.chunk_index,
        content=hit.content,
        score=hit.score,
        source=hit.source,
        metadata=dict(hit.metadata),
    )


def _to_citation_response(citation: Citation) -> CitationResponse:
    return CitationResponse(
        id=citation.id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        chunk_index=citation.chunk_index,
        content=citation.content,
        score=citation.score,
        source=citation.source,
        metadata=dict(citation.metadata),
    )


def _pgvector_literal(vector: Sequence[float]) -> str:
    values = [float(value) for value in vector]
    if not values:
        raise AppError("Query embedding cannot be empty.", code="empty_embedding", status_code=502)
    if any(not math.isfinite(value) for value in values):
        raise AppError(
            "Query embedding contains an invalid number.",
            code="invalid_embedding",
            status_code=502,
        )
    return "[" + ",".join(str(value) for value in values) + "]"


def _metadata_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key, item in value.items():
        metadata[str(key)] = item
    return metadata


def _add_if_present(metadata: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        metadata[key] = value


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
