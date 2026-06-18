from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from fishrag_api.api.dependencies import CurrentUser, get_current_user, get_session
from fishrag_api.db.models import Approval, new_id, utc_now
from fishrag_api.main import create_app


class FakeApprovalScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def scalars(self) -> FakeApprovalScalarResult:
        return self

    def all(self) -> list[Any]:
        return self.items


class FakeApprovalSession:
    def __init__(self) -> None:
        self.approvals: dict[str, Approval] = {}
        self.commit_count = 0

    def add(self, approval: Approval) -> None:
        now = utc_now()
        approval.id = approval.id or new_id()
        approval.created_at = approval.created_at or now
        self.approvals[approval.id] = approval

    async def get(self, model: type[Approval], approval_id: str) -> Approval | None:
        if model is Approval:
            return self.approvals.get(approval_id)
        return None

    async def execute(self, _: object) -> FakeApprovalScalarResult:
        return FakeApprovalScalarResult(
            sorted(self.approvals.values(), key=lambda item: item.created_at, reverse=True)
        )

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _: object) -> None:
        return None


def test_approvals_api_create_list_and_approve_with_modified_input() -> None:
    fake_session = FakeApprovalSession()
    app = create_app()
    current_user = CurrentUser(id="requester-1", role="member")

    async def override_session() -> AsyncIterator[FakeApprovalSession]:
        yield fake_session

    def override_user() -> CurrentUser:
        return current_user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)

    create_response = client.post(
        "/api/v1/approvals",
        json={
            "tool_name": "delete_document",
            "tool_input": {"document_id": "doc-1"},
            "reason": "删除知识库文档",
            "risk_level": "high",
            "categories": ["knowledge_base_mutation"],
        },
    )

    assert create_response.status_code == 201
    approval_id = create_response.json()["id"]
    assert create_response.json()["status"] == "pending"
    assert create_response.json()["tool_input"]["risk"]["risk_level"] == "high"

    list_response = client.get("/api/v1/approvals?status=pending")

    assert list_response.status_code == 200
    assert len(list_response.json()["approvals"]) == 1

    current_user = CurrentUser(id="reviewer-1", role="reviewer")
    decision_response = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={
            "decision": "approved",
            "decision_reason": "只允许归档，不允许物理删除",
            "modified_tool_input": {"document_id": "doc-1", "mode": "archive"},
        },
    )

    assert decision_response.status_code == 200
    body = decision_response.json()
    assert body["status"] == "approved"
    assert body["reviewer_user_id"] == "reviewer-1"
    assert body["resumable_tool_call"] == {
        "name": "delete_document",
        "arguments": {"document_id": "doc-1", "mode": "archive"},
    }
    assert [item["action"] for item in body["tool_input"]["audit"]] == [
        "created",
        "approved",
    ]
    assert fake_session.commit_count == 2


def test_approvals_api_rejects_member_decision() -> None:
    fake_session = FakeApprovalSession()
    app = create_app()

    async def override_session() -> AsyncIterator[FakeApprovalSession]:
        yield fake_session

    def override_user() -> CurrentUser:
        return CurrentUser(id="member-1", role="member")

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)

    create_response = client.post(
        "/api/v1/approvals",
        json={"tool_name": "shell", "tool_input": {"cmd": "danger"}},
    )
    approval_id = create_response.json()["id"]

    decision_response = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "rejected", "decision_reason": "No"},
    )

    assert decision_response.status_code == 403
    assert decision_response.json()["error"]["code"] == "approval_forbidden"
