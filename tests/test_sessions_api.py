from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import CurrentUser, get_current_user, get_session
from fishrag_api.db.models import ChatSession, Message, new_id, utc_now
from fishrag_api.main import create_app


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def scalars(self) -> FakeScalarResult:
        return self

    def all(self) -> list[Any]:
        return self.items


class FakeSessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.messages: dict[str, list[Message]] = {}
        self.commit_count = 0

    def add(self, item: ChatSession | Message) -> None:
        now = utc_now()
        if isinstance(item, ChatSession):
            item.id = item.id or new_id()
            item.created_at = item.created_at or now
            item.updated_at = item.updated_at or now
            self.sessions[item.id] = item
        else:
            item.id = item.id or new_id()
            item.created_at = item.created_at or now
            self.messages.setdefault(item.session_id, []).append(item)

    async def get(self, model: type[ChatSession] | type[Message], item_id: str) -> Any | None:
        if model is ChatSession:
            return self.sessions.get(item_id)
        for messages in self.messages.values():
            for message in messages:
                if message.id == item_id:
                    return message
        return None

    async def execute(self, statement: object) -> FakeScalarResult:
        rendered = str(statement)
        if "FROM messages" in rendered:
            all_messages = [
                message
                for messages in self.messages.values()
                for message in messages
            ]
            return FakeScalarResult(sorted(all_messages, key=lambda item: item.created_at))
        sessions = [
            session
            for session in self.sessions.values()
            if session.status != "deleted"
        ]
        return FakeScalarResult(sorted(sessions, key=lambda item: item.updated_at, reverse=True))

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _: object) -> None:
        return None


def test_sessions_api_lifecycle_messages_and_summary() -> None:
    fake_session = FakeSessionStore()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeSessionStore]:
        yield fake_session

    def override_user() -> CurrentUser:
        return CurrentUser(id="user-1", role="member")

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)

    create_response = client.post("/api/v1/sessions", json={"title": "病例讨论"})

    assert create_response.status_code == 201
    session_id = create_response.json()["id"]
    assert create_response.json()["status"] == "active"

    user_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"role": "user", "content": "高血压如何用药？"},
    )
    assistant_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "role": "assistant",
            "content": "需要结合指南证据回答。",
            "metadata": {"citations": ["C1"]},
        },
    )

    assert user_message_response.status_code == 201
    assert assistant_message_response.status_code == 201
    assert assistant_message_response.json()["metadata"] == {"citations": ["C1"]}

    summary_response = client.post(
        f"/api/v1/sessions/{session_id}/summary",
        json={"max_messages": 10, "max_chars": 500},
    )

    assert summary_response.status_code == 200
    assert "user: 高血压如何用药？" in summary_response.json()["summary"]
    assert "assistant: 需要结合指南证据回答。" in summary_response.json()["summary"]

    archive_response = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "高血压讨论", "status": "archived"},
    )
    delete_response = client.delete(f"/api/v1/sessions/{session_id}")
    restore_response = client.post(f"/api/v1/sessions/{session_id}/restore")
    detail_response = client.get(f"/api/v1/sessions/{session_id}")

    assert archive_response.json()["title"] == "高血压讨论"
    assert archive_response.json()["status"] == "archived"
    assert delete_response.json()["status"] == "deleted"
    assert restore_response.json()["status"] == "active"
    assert detail_response.status_code == 200
    assert len(detail_response.json()["messages"]) == 2
    assert fake_session.commit_count == 7
