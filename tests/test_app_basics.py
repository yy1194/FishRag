from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fishrag_api.core.errors import AppError
from fishrag_api.core.security import create_access_token
from fishrag_api.main import create_app
from fishrag_api.observability import metrics_registry


def test_health_response_includes_request_id_header() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_health_response_includes_traceparent_header() -> None:
    client = TestClient(create_app())
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"

    response = client.get(
        "/api/v1/health",
        headers={"traceparent": f"00-{trace_id}-00f067aa0ba902b7-01"},
    )

    assert response.status_code == 200
    assert response.headers["traceparent"].startswith(f"00-{trace_id}-")


def test_metrics_endpoint_exports_prometheus_metrics() -> None:
    metrics_registry.reset()
    client = TestClient(create_app())

    client.get("/api/v1/health")
    response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    body = response.text
    assert "fishrag_app_info" in body
    assert "fishrag_http_requests_total" in body
    assert "fishrag_http_request_duration_seconds_bucket" in body
    assert 'method="GET"' in body
    assert 'status_code="200"' in body


def test_app_error_response_shape() -> None:
    app: FastAPI = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise AppError("Boom", code="boom", status_code=418)

    response = TestClient(app).get("/boom")

    assert response.status_code == 418
    assert response.json()["error"]["code"] == "boom"
    assert "request_id" in response.json()["error"]


def test_auth_me_reads_bearer_token() -> None:
    token = create_access_token(subject="user-123", role="reviewer")
    response = TestClient(create_app()).get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"id": "user-123", "role": "reviewer"}
