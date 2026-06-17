from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fishrag_api.core.errors import AppError
from fishrag_api.core.security import create_access_token
from fishrag_api.main import create_app


def test_health_response_includes_request_id_header() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"


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
