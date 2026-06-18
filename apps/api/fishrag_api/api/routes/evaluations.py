from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body
from fishrag_rag.evaluation import (
    RagAggregateScores,
    RagEvaluationExample,
    RagEvaluationExampleResult,
    RagEvaluationReport,
    evaluate_rag_dataset,
)
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


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


@router.post("/rag/score", response_model=RagEvaluationResponse)
async def score_rag_evaluation(
    request: Annotated[RagEvaluationRequest, Body()],
) -> RagEvaluationResponse:
    report = evaluate_rag_dataset(
        [_to_domain_example(example) for example in request.examples],
        ks=request.ks,
    )
    return _to_response(report)


def _to_domain_example(example: RagEvaluationExampleRequest) -> RagEvaluationExample:
    return RagEvaluationExample(
        id=example.id,
        query=example.query,
        relevant_chunk_ids=frozenset(example.relevant_chunk_ids),
        retrieved_chunk_ids=tuple(example.retrieved_chunk_ids),
        cited_chunk_ids=tuple(example.cited_chunk_ids),
        answer=example.answer,
    )


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
