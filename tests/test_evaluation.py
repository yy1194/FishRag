from __future__ import annotations

import math

from fishrag_rag.evaluation import (
    RagEvaluationExample,
    citation_coverage,
    evaluate_rag_dataset,
    evaluate_rag_example,
    faithfulness_score,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_retrieval_metrics_handle_ranked_relevance_and_duplicates() -> None:
    retrieved = ["chunk-irrelevant", "chunk-a", "chunk-b", "chunk-a"]
    relevant = frozenset({"chunk-a", "chunk-b"})

    assert recall_at_k(retrieved, relevant, 1) == 0.0
    assert recall_at_k(retrieved, relevant, 2) == 0.5
    assert recall_at_k(retrieved, relevant, 3) == 1.0
    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert mean_reciprocal_rank(retrieved, relevant) == 0.5
    assert math.isclose(ndcg_at_k(retrieved, relevant, 3), 0.693426, rel_tol=1e-5)


def test_citation_metrics_penalize_unsupported_citations() -> None:
    relevant = frozenset({"chunk-a", "chunk-b"})

    assert citation_coverage(["chunk-a", "chunk-missing"], relevant) == 0.5
    assert (
        faithfulness_score(
            answer="Supported answer [C1].",
            cited_chunk_ids=["chunk-a", "chunk-missing"],
            retrieved_chunk_ids=["chunk-a", "chunk-b"],
            relevant_chunk_ids=relevant,
        )
        == 0.5
    )


def test_unanswerable_example_scores_well_when_nothing_is_retrieved_or_cited() -> None:
    example = RagEvaluationExample(
        id="missing",
        query="No evidence question",
        relevant_chunk_ids=frozenset(),
        retrieved_chunk_ids=(),
        cited_chunk_ids=(),
        answer="",
    )

    result = evaluate_rag_example(example, ks=[1, 5])

    assert result.scores.recall_at_k == {1: 1.0, 5: 1.0}
    assert result.scores.precision_at_k == {1: 1.0, 5: 1.0}
    assert result.scores.ndcg_at_k == {1: 1.0, 5: 1.0}
    assert result.scores.mrr == 1.0
    assert result.scores.citation_coverage == 1.0
    assert result.scores.faithfulness == 1.0


def test_evaluate_rag_dataset_aggregates_scores() -> None:
    report = evaluate_rag_dataset(
        [
            RagEvaluationExample(
                id="partially-found",
                query="question",
                relevant_chunk_ids=frozenset({"chunk-a", "chunk-b"}),
                retrieved_chunk_ids=("chunk-irrelevant", "chunk-a", "chunk-b"),
                cited_chunk_ids=("chunk-a",),
                answer="Answer [C1].",
            ),
            RagEvaluationExample(
                id="missing",
                query="missing question",
                relevant_chunk_ids=frozenset(),
                retrieved_chunk_ids=(),
                cited_chunk_ids=(),
                answer="",
            ),
        ],
        ks=[1, 2, 3],
    )

    assert report.ks == (1, 2, 3)
    assert report.aggregate.total_examples == 2
    assert report.aggregate.answered_examples == 1
    assert report.aggregate.recall_at_k[2] == 0.75
    assert report.aggregate.citation_coverage == 0.75
    assert report.examples[0].scores.relevant_retrieved == 2
