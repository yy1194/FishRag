from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

DEFAULT_EVALUATION_KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class RagEvaluationExample:
    id: str
    query: str
    relevant_chunk_ids: frozenset[str]
    retrieved_chunk_ids: tuple[str, ...]
    cited_chunk_ids: tuple[str, ...] = field(default_factory=tuple)
    answer: str = ""


@dataclass(frozen=True)
class RagExampleScores:
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


@dataclass(frozen=True)
class RagEvaluationExampleResult:
    example: RagEvaluationExample
    scores: RagExampleScores


@dataclass(frozen=True)
class RagAggregateScores:
    recall_at_k: dict[int, float]
    precision_at_k: dict[int, float]
    ndcg_at_k: dict[int, float]
    mrr: float
    faithfulness: float
    citation_coverage: float
    total_examples: int
    answered_examples: int


@dataclass(frozen=True)
class RagEvaluationReport:
    ks: tuple[int, ...]
    examples: list[RagEvaluationExampleResult]
    aggregate: RagAggregateScores


def evaluate_rag_dataset(
    examples: Sequence[RagEvaluationExample],
    *,
    ks: Sequence[int] = DEFAULT_EVALUATION_KS,
) -> RagEvaluationReport:
    selected_ks = normalize_ks(ks)
    results = [evaluate_rag_example(example, ks=selected_ks) for example in examples]
    return RagEvaluationReport(
        ks=selected_ks,
        examples=results,
        aggregate=_aggregate_scores(results, ks=selected_ks),
    )


def evaluate_rag_example(
    example: RagEvaluationExample,
    *,
    ks: Sequence[int] = DEFAULT_EVALUATION_KS,
) -> RagEvaluationExampleResult:
    selected_ks = normalize_ks(ks)
    retrieved = _unique_ordered(example.retrieved_chunk_ids)
    cited = _unique_ordered(example.cited_chunk_ids)
    relevant = example.relevant_chunk_ids

    recall = {k: recall_at_k(retrieved, relevant, k) for k in selected_ks}
    precision = {k: precision_at_k(retrieved, relevant, k) for k in selected_ks}
    ndcg = {k: ndcg_at_k(retrieved, relevant, k) for k in selected_ks}
    cited_relevant = len(set(cited) & relevant)

    return RagEvaluationExampleResult(
        example=example,
        scores=RagExampleScores(
            recall_at_k=recall,
            precision_at_k=precision,
            ndcg_at_k=ndcg,
            mrr=mean_reciprocal_rank(retrieved, relevant),
            faithfulness=faithfulness_score(
                answer=example.answer,
                cited_chunk_ids=cited,
                retrieved_chunk_ids=retrieved,
                relevant_chunk_ids=relevant,
            ),
            citation_coverage=citation_coverage(cited, relevant),
            relevant_retrieved=len(set(retrieved) & relevant),
            relevant_cited=cited_relevant,
            retrieved_count=len(retrieved),
            cited_count=len(cited),
        ),
    )


def normalize_ks(ks: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(sorted({int(k) for k in ks if int(k) > 0}))
    if not normalized:
        return DEFAULT_EVALUATION_KS
    return normalized


def recall_at_k(
    retrieved_chunk_ids: Sequence[str],
    relevant_chunk_ids: frozenset[str],
    k: int,
) -> float:
    retrieved = _unique_ordered(retrieved_chunk_ids)[:k]
    if not relevant_chunk_ids:
        return 1.0 if not retrieved else 0.0
    return len(set(retrieved) & relevant_chunk_ids) / len(relevant_chunk_ids)


def precision_at_k(
    retrieved_chunk_ids: Sequence[str],
    relevant_chunk_ids: frozenset[str],
    k: int,
) -> float:
    retrieved = _unique_ordered(retrieved_chunk_ids)[:k]
    if not retrieved:
        return 1.0 if not relevant_chunk_ids else 0.0
    return len(set(retrieved) & relevant_chunk_ids) / len(retrieved)


def mean_reciprocal_rank(
    retrieved_chunk_ids: Sequence[str],
    relevant_chunk_ids: frozenset[str],
) -> float:
    retrieved = _unique_ordered(retrieved_chunk_ids)
    if not relevant_chunk_ids:
        return 1.0 if not retrieved else 0.0
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant_chunk_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved_chunk_ids: Sequence[str],
    relevant_chunk_ids: frozenset[str],
    k: int,
) -> float:
    retrieved = _unique_ordered(retrieved_chunk_ids)[:k]
    if not relevant_chunk_ids:
        return 1.0 if not retrieved else 0.0
    gains = [1.0 if chunk_id in relevant_chunk_ids else 0.0 for chunk_id in retrieved]
    dcg = _discounted_cumulative_gain(gains)
    ideal_relevant_count = min(len(relevant_chunk_ids), k)
    idcg = _discounted_cumulative_gain([1.0] * ideal_relevant_count)
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def citation_coverage(
    cited_chunk_ids: Sequence[str],
    relevant_chunk_ids: frozenset[str],
) -> float:
    cited = set(_unique_ordered(cited_chunk_ids))
    if not relevant_chunk_ids:
        return 1.0 if not cited else 0.0
    return len(cited & relevant_chunk_ids) / len(relevant_chunk_ids)


def faithfulness_score(
    *,
    answer: str,
    cited_chunk_ids: Sequence[str],
    retrieved_chunk_ids: Sequence[str],
    relevant_chunk_ids: frozenset[str],
) -> float:
    cited = set(_unique_ordered(cited_chunk_ids))
    retrieved = set(_unique_ordered(retrieved_chunk_ids))
    if not answer.strip():
        return 1.0 if not relevant_chunk_ids and not cited else 0.0
    if not cited:
        return 0.0 if relevant_chunk_ids else 1.0
    supported_citations = cited & retrieved & relevant_chunk_ids
    return len(supported_citations) / len(cited)


def _aggregate_scores(
    results: Sequence[RagEvaluationExampleResult],
    *,
    ks: Sequence[int],
) -> RagAggregateScores:
    if not results:
        empty_by_k = {k: 0.0 for k in ks}
        return RagAggregateScores(
            recall_at_k=empty_by_k,
            precision_at_k=dict(empty_by_k),
            ndcg_at_k=dict(empty_by_k),
            mrr=0.0,
            faithfulness=0.0,
            citation_coverage=0.0,
            total_examples=0,
            answered_examples=0,
        )

    total = len(results)
    return RagAggregateScores(
        recall_at_k={
            k: _mean(result.scores.recall_at_k[k] for result in results) for k in ks
        },
        precision_at_k={
            k: _mean(result.scores.precision_at_k[k] for result in results) for k in ks
        },
        ndcg_at_k={k: _mean(result.scores.ndcg_at_k[k] for result in results) for k in ks},
        mrr=_mean(result.scores.mrr for result in results),
        faithfulness=_mean(result.scores.faithfulness for result in results),
        citation_coverage=_mean(result.scores.citation_coverage for result in results),
        total_examples=total,
        answered_examples=sum(1 for result in results if result.example.answer.strip()),
    )


def _discounted_cumulative_gain(gains: Sequence[float]) -> float:
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))


def _mean(values: Iterable[float]) -> float:
    numeric_values = list(values)
    if not numeric_values:
        return 0.0
    return sum(numeric_values) / len(numeric_values)


def _unique_ordered(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return tuple(unique)
