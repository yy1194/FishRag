from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import CurrentUser, get_current_user, get_session
from fishrag_api.db.models import Memory, new_id, utc_now
from fishrag_api.main import create_app


class FakeMemoryScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def scalars(self) -> FakeMemoryScalarResult:
        return self

    def all(self) -> list[Any]:
        return self.items


class FakeMemorySession:
    def __init__(self) -> None:
        self.memories: dict[str, Memory] = {}
        self.commit_count = 0

    def add(self, memory: Memory) -> None:
        now = utc_now()
        memory.id = memory.id or new_id()
        memory.created_at = memory.created_at or now
        memory.updated_at = memory.updated_at or now
        self.memories[memory.id] = memory

    async def get(self, model: type[Memory], memory_id: str) -> Memory | None:
        if model is Memory:
            return self.memories.get(memory_id)
        return None

    async def execute(self, _: object) -> FakeMemoryScalarResult:
        return FakeMemoryScalarResult(
            sorted(self.memories.values(), key=lambda item: item.updated_at, reverse=True)
        )

    async def delete(self, memory: Memory) -> None:
        self.memories.pop(memory.id, None)

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _: object) -> None:
        return None


def test_memories_api_crud_enabled_filter_and_audit() -> None:
    fake_session = FakeMemorySession()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeMemorySession]:
        yield fake_session

    def override_user() -> CurrentUser:
        return CurrentUser(id="user-1", role="member")

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)

    create_response = client.post(
        "/api/v1/memories",
        json={
            "scope": "profile",
            "key": "output_style",
            "value": "喜欢分步骤输出",
            "enabled": False,
            "metadata": {"source": "manual"},
        },
    )

    assert create_response.status_code == 201
    memory_id = create_response.json()["id"]
    assert not create_response.json()["enabled"]
    assert create_response.json()["metadata"]["audit"][0]["action"] == "created"

    hidden_list_response = client.get("/api/v1/memories")

    assert hidden_list_response.status_code == 200
    assert hidden_list_response.json()["memories"] == []

    all_list_response = client.get("/api/v1/memories?enabled_only=false&query=输出")

    assert len(all_list_response.json()["memories"]) == 1

    update_response = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"enabled": True, "value": "喜欢简洁分步骤输出"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["enabled"]
    assert update_response.json()["value"] == "喜欢简洁分步骤输出"
    assert [item["action"] for item in update_response.json()["metadata"]["audit"]] == [
        "created",
        "updated",
    ]

    visible_list_response = client.get("/api/v1/memories?query=简洁")

    assert len(visible_list_response.json()["memories"]) == 1

    delete_response = client.delete(f"/api/v1/memories/{memory_id}")

    assert delete_response.status_code == 204
    assert fake_session.memories == {}
    assert fake_session.commit_count == 3
