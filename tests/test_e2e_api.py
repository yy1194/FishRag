from __future__ import annotations

from fastapi.testclient import TestClient
from fishrag_api.main import create_app
from fishrag_api.observability import metrics_registry


def test_e2e_health_evaluation_and_metrics_flow() -> None:
    metrics_registry.reset()
    client = TestClient(create_app())
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"

    health_response = client.get(
        "/api/v1/health",
        headers={
            "X-Request-ID": "e2e-request-id",
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        },
    )
    score_response = client.post(
        "/api/v1/evaluations/rag/score",
        json={
            "ks": [1, 3],
            "examples": [
                {
                    "id": "e2e-case",
                    "query": "How should an answer cite retrieved evidence?",
                    "relevant_chunk_ids": ["chunk-a"],
                    "retrieved_chunk_ids": ["chunk-a", "chunk-b"],
                    "cited_chunk_ids": ["chunk-a"],
                    "answer": "Use grounded evidence [C1].",
                }
            ],
        },
    )
    metrics_response = client.get("/api/v1/metrics")

    assert health_response.status_code == 200
    assert health_response.headers["X-Request-ID"] == "e2e-request-id"
    assert health_response.headers["traceparent"].startswith(f"00-{trace_id}-")
    assert score_response.status_code == 200
    assert score_response.json()["aggregate"]["recall_at_k"]["1"] == 1.0
    assert metrics_response.status_code == 200
    assert 'path="/health"' in metrics_response.text
    assert 'path="/evaluations/rag/score"' in metrics_response.text
