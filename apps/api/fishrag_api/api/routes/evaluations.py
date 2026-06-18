from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status
from fishrag_agent.approval import apply_medical_safety_guard
from fishrag_common.config import Settings, get_settings
from fishrag_rag.embeddings import EmbeddingClient
from fishrag_rag.evaluation import (
    RagAggregateScores,
    RagEvaluationExample,
    RagEvaluationExampleResult,
    RagEvaluationReport,
    evaluate_rag_dataset,
    normalize_ks,
)
from fishrag_rag.generation import ChatClient, ChatGenerationError, generate_rag_answer
from fishrag_rag.keyword_index import KeywordIndexClient
from fishrag_rag.rerankers import RerankerClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import (
    get_chat_client,
    get_embedding_client,
    get_keyword_index_client,
    get_reranker_client,
    get_session,
)
from fishrag_api.api.routes.rag import RagSearchRequest, _run_hybrid_search
from fishrag_api.core.errors import AppError
from fishrag_api.services.evaluations import (
    InMemoryRagEvaluationJobStore,
    RagEvaluationJobMode,
    RagEvaluationJobRecord,
    RagEvaluationJobStatus,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
evaluation_job_store = InMemoryRagEvaluationJobStore()

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbeddingClientDep = Annotated[EmbeddingClient, Depends(get_embedding_client)]
KeywordIndexClientDep = Annotated[KeywordIndexClient, Depends(get_keyword_index_client)]
RerankerClientDep = Annotated[RerankerClient, Depends(get_reranker_client)]
ChatClientDep = Annotated[ChatClient, Depends(get_chat_client)]


class RagEvaluationExampleRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=4000)
    relevant_chunk_ids: list[str] = Field(default_factory=list, max_length=200)
    retrieved_chunk_ids: list[str] = Field(default_factory=list, max_length=500)
    cited_chunk_ids: list[str] = Field(default_factory=list, max_length=200)
    answer: str = Field(default="", max_length=20000)

    model_config = ConfigDict(extra="forbid")


class RagEvaluationRequest(BaseModel):
    examples: list[RagEvaluationExampleRequest] = Field(min_length=1, max_length=1000)
    ks: list[int] = Field(default_factory=lambda: [1, 3, 5, 10], max_length=20)

    model_config = ConfigDict(extra="forbid")


class RagEvaluationJobCreateRequest(BaseModel):
    name: str = Field(default="RAG Evaluation", min_length=1, max_length=255)
    examples: list[RagEvaluationExampleRequest] = Field(default_factory=list, max_length=1000)
    dataset_jsonl: str | None = Field(default=None, max_length=5_000_000)
    ks: list[int] = Field(default_factory=lambda: [1, 3, 5, 10], max_length=20)
    run_rag: bool = True
    vector_limit: int = Field(default=20, ge=1, le=100)
    keyword_limit: int = Field(default=20, ge=1, le=100)
    limit: int = Field(default=10, ge=1, le=50)
    use_reranker: bool = True
    reranker_top_n: int = Field(default=10, ge=1, le=50)

    model_config = ConfigDict(extra="forbid")


class RagExampleScoresResponse(BaseModel):
    recall_at_k: dict[int, float]
    precision_at_k: dict[int, float]
    ndcg_at_k: dict[int, float]
    mrr: float
    faithfulness: float
    citation_coverage: float
    relevant_retrieved: int
    relevant_cited: int
    retrieved_count: int
    cited_count: int


class RagEvaluationExampleResponse(BaseModel):
    id: str
    query: str
    scores: RagExampleScoresResponse


class RagAggregateScoresResponse(BaseModel):
    recall_at_k: dict[int, float]
    precision_at_k: dict[int, float]
    ndcg_at_k: dict[int, float]
    mrr: float
    faithfulness: float
    citation_coverage: float
    total_examples: int
    answered_examples: int


class RagEvaluationResponse(BaseModel):
    ks: list[int]
    aggregate: RagAggregateScoresResponse
    examples: list[RagEvaluationExampleResponse]


class RagEvaluationJobResponse(BaseModel):
    id: str
    name: str
    status: RagEvaluationJobStatus
    mode: RagEvaluationJobMode
    ks: list[int]
    example_count: int
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    report: RagEvaluationResponse | None = None


class RagEvaluationJobListResponse(BaseModel):
    jobs: list[RagEvaluationJobResponse]


@router.post("/rag/score", response_model=RagEvaluationResponse)
async def score_rag_evaluation(
    request: Annotated[RagEvaluationRequest, Body()],
) -> RagEvaluationResponse:
    report = evaluate_rag_dataset(
        [_to_domain_example(example) for example in request.examples],
        ks=request.ks,
    )
    return _to_response(report)


@router.post(
    "/rag/jobs",
    response_model=RagEvaluationJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rag_evaluation_job(
    request: Annotated[RagEvaluationJobCreateRequest, Body()],
    session: DbSession,
    settings: SettingsDep,
    embedding_client: EmbeddingClientDep,
    keyword_index_client: KeywordIndexClientDep,
    reranker_client: RerankerClientDep,
    chat_client: ChatClientDep,
) -> RagEvaluationJobResponse:
    request_examples = _load_request_examples(request)
    ks = normalize_ks(request.ks)
    mode: RagEvaluationJobMode = "auto_rag" if request.run_rag else "scored_dataset"
    job = evaluation_job_store.create(
        name=request.name,
        mode=mode,
        ks=ks,
        example_count=len(request_examples),
    )
    try:
        evaluation_examples = await _materialize_evaluation_examples(
            request=request,
            examples=request_examples,
            session=session,
            settings=settings,
            embedding_client=embedding_client,
            keyword_index_client=keyword_index_client,
            reranker_client=reranker_client,
            chat_client=chat_client,
        )
        report = evaluate_rag_dataset(evaluation_examples, ks=ks)
    except (AppError, ChatGenerationError) as exc:
        failed_job = evaluation_job_store.fail(job.id, error=str(exc))
        return _to_job_response(failed_job)

    completed_job = evaluation_job_store.complete(job.id, report=report)
    return _to_job_response(completed_job)


@router.get("/rag/jobs", response_model=RagEvaluationJobListResponse)
async def list_rag_evaluation_jobs(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RagEvaluationJobListResponse:
    return RagEvaluationJobListResponse(
        jobs=[_to_job_response(job) for job in evaluation_job_store.list(limit=limit)]
    )


@router.get("/rag/jobs/{job_id}", response_model=RagEvaluationJobResponse)
async def get_rag_evaluation_job(job_id: str) -> RagEvaluationJobResponse:
    try:
        job = evaluation_job_store.get(job_id)
    except ValueError as exc:
        raise AppError(str(exc), code="rag_evaluation_job_not_found", status_code=404) from exc
    return _to_job_response(job)


def _to_domain_example(example: RagEvaluationExampleRequest) -> RagEvaluationExample:
    return RagEvaluationExample(
        id=example.id,
        query=example.query,
        relevant_chunk_ids=frozenset(example.relevant_chunk_ids),
        retrieved_chunk_ids=tuple(example.retrieved_chunk_ids),
        cited_chunk_ids=tuple(example.cited_chunk_ids),
        answer=example.answer,
    )


def _load_request_examples(
    request: RagEvaluationJobCreateRequest,
) -> list[RagEvaluationExampleRequest]:
    examples = list(request.examples)
    if request.dataset_jsonl is not None:
        examples.extend(_parse_jsonl_examples(request.dataset_jsonl))
    if not examples:
        raise AppError(
            "RAG evaluation dataset cannot be empty.",
            code="rag_evaluation_dataset_empty",
        )
    return examples


def _parse_jsonl_examples(dataset_jsonl: str) -> list[RagEvaluationExampleRequest]:
    examples: list[RagEvaluationExampleRequest] = []
    for line_number, raw_line in enumerate(dataset_jsonl.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            examples.append(RagEvaluationExampleRequest.model_validate_json(line))
        except ValidationError as exc:
            raise AppError(
                "Invalid RAG evaluation JSONL example.",
                code="invalid_rag_evaluation_jsonl",
                details={"line": line_number, "message": str(exc)},
            ) from exc
    return examples


async def _materialize_evaluation_examples(
    *,
    request: RagEvaluationJobCreateRequest,
    examples: list[RagEvaluationExampleRequest],
    session: AsyncSession,
    settings: Settings,
    embedding_client: EmbeddingClient,
    keyword_index_client: KeywordIndexClient,
    reranker_client: RerankerClient,
    chat_client: ChatClient,
) -> list[RagEvaluationExample]:
    if not request.run_rag:
        return [_to_domain_example(example) for example in examples]

    materialized: list[RagEvaluationExample] = []
    for example in examples:
        search_request = RagSearchRequest(
            query=example.query,
            vector_limit=request.vector_limit,
            keyword_limit=request.keyword_limit,
            limit=request.limit,
            use_reranker=request.use_reranker,
            reranker_top_n=request.reranker_top_n,
        )
        search_result = await _run_hybrid_search(
            request=search_request,
            session=session,
            settings=settings,
            embedding_client=embedding_client,
            keyword_index_client=keyword_index_client,
            reranker_client=reranker_client,
        )
        answer = await generate_rag_answer(
            query=example.query,
            hits=search_result.hits,
            citations=search_result.citations,
            chat_client=chat_client,
        )
        guarded = apply_medical_safety_guard(
            query=example.query,
            answer=answer.answer,
            citation_count=len(answer.citations),
        )
        materialized.append(
            RagEvaluationExample(
                id=example.id,
                query=example.query,
                relevant_chunk_ids=frozenset(example.relevant_chunk_ids),
                retrieved_chunk_ids=tuple(hit.chunk_id for hit in search_result.hits),
                cited_chunk_ids=tuple(citation.chunk_id for citation in answer.citations),
                answer=guarded.answer,
            )
        )
    return materialized


def _to_response(report: RagEvaluationReport) -> RagEvaluationResponse:
    return RagEvaluationResponse(
        ks=list(report.ks),
        aggregate=_to_aggregate_response(report.aggregate),
        examples=[_to_example_response(result) for result in report.examples],
    )


def _to_example_response(result: RagEvaluationExampleResult) -> RagEvaluationExampleResponse:
    scores = result.scores
    return RagEvaluationExampleResponse(
        id=result.example.id,
        query=result.example.query,
        scores=RagExampleScoresResponse(
            recall_at_k=scores.recall_at_k,
            precision_at_k=scores.precision_at_k,
            ndcg_at_k=scores.ndcg_at_k,
            mrr=scores.mrr,
            faithfulness=scores.faithfulness,
            citation_coverage=scores.citation_coverage,
            relevant_retrieved=scores.relevant_retrieved,
            relevant_cited=scores.relevant_cited,
            retrieved_count=scores.retrieved_count,
            cited_count=scores.cited_count,
        ),
    )


def _to_aggregate_response(aggregate: RagAggregateScores) -> RagAggregateScoresResponse:
    return RagAggregateScoresResponse(
        recall_at_k=aggregate.recall_at_k,
        precision_at_k=aggregate.precision_at_k,
        ndcg_at_k=aggregate.ndcg_at_k,
        mrr=aggregate.mrr,
        faithfulness=aggregate.faithfulness,
        citation_coverage=aggregate.citation_coverage,
        total_examples=aggregate.total_examples,
        answered_examples=aggregate.answered_examples,
    )


def _to_job_response(job: RagEvaluationJobRecord) -> RagEvaluationJobResponse:
    return RagEvaluationJobResponse(
        id=job.id,
        name=job.name,
        status=job.status,
        mode=job.mode,
        ks=list(job.ks),
        example_count=job.example_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
        report=_to_response(job.report) if job.report is not None else None,
    )
