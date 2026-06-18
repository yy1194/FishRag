from __future__ import annotations

from fastapi.testclient import TestClient
from fishrag_api.main import create_app


def test_score_rag_evaluation_api_returns_aggregate_and_example_scores() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/evaluations/rag/score",
        json={
            "ks": [1, 2, 3],
            "examples": [
                {
                    "id": "hypertension-guideline",
                    "query": "How should hypertension guideline evidence be cited?",
                    "relevant_chunk_ids": ["chunk-a", "chunk-b"],
                    "retrieved_chunk_ids": ["chunk-irrelevant", "chunk-a", "chunk-b"],
                    "cited_chunk_ids": ["chunk-a"],
                    "answer": "Use the cited guideline evidence [C1].",
                },
                {
                    "id": "unknown-topic",
                    "query": "Question without knowledge base evidence",
                    "relevant_chunk_ids": [],
                    "retrieved_chunk_ids": [],
                    "cited_chunk_ids": [],
                    "answer": "",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ks"] == [1, 2, 3]
    assert body["aggregate"]["total_examples"] == 2
    assert body["aggregate"]["answered_examples"] == 1
    assert body["aggregate"]["recall_at_k"]["2"] == 0.75
    assert body["aggregate"]["citation_coverage"] == 0.75
    assert body["examples"][0]["id"] == "hypertension-guideline"
    assert body["examples"][0]["scores"]["relevant_retrieved"] == 2


def test_score_rag_evaluation_api_rejects_empty_dataset() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/evaluations/rag/score",
        json={"examples": []},
    )

    assert response.status_code == 422
