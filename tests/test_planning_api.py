from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from fishrag_api.main import create_app


def test_planning_api_write_read_and_delete_todos() -> None:
    client = TestClient(create_app())
    session_id = "api-session"

    write_response = client.put(
        f"/api/v1/planning/sessions/{session_id}/todos",
        json={
            "todos": [
                {"id": "1", "content": "拆解任务", "status": "completed"},
                {"id": "2", "content": "实现 write_todos", "status": "in_progress"},
            ]
        },
    )

    assert write_response.status_code == 200
    body = write_response.json()
    assert body["session_id"] == session_id
    assert body["stats"]["total"] == 2
    assert body["stats"]["completed"] == 1
    assert body["stats"]["in_progress"] == 1

    read_response = client.get(f"/api/v1/planning/sessions/{session_id}/todos")

    assert read_response.status_code == 200
    assert read_response.json()["todos"][1]["content"] == "实现 write_todos"

    delete_response = client.delete(f"/api/v1/planning/sessions/{session_id}/todos")

    assert delete_response.status_code == 200
    assert delete_response.json()["todos"] == []


def test_planning_api_rejects_duplicate_todo_ids() -> None:
    client = TestClient(create_app())

    response = client.put(
        "/api/v1/planning/sessions/duplicate-session/todos",
        json={
            "todos": [
                {"id": "1", "content": "A", "status": "pending"},
                {"id": "1", "content": "B", "status": "pending"},
            ]
        },
    )

    assert response.status_code == 400
    assert "Duplicate todo id" in response.json()["error"]["message"]
