from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import CurrentUser, get_current_user, get_session
from fishrag_api.core.errors import AppError
from fishrag_api.db.models import Approval, utc_now
from fishrag_api.services.approvals import create_approval_record

router = APIRouter(prefix="/approvals", tags=["approvals"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
ApprovalStatus = Literal["pending", "approved", "rejected"]
ApprovalDecision = Literal["approved", "rejected"]


class ApprovalCreateRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=255)
    tool_input: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=2000)
    risk_level: str = Field(default="high", min_length=1, max_length=32)
    categories: list[str] = Field(default_factory=list, max_length=20)

    model_config = ConfigDict(extra="forbid")


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision
    decision_reason: str | None = Field(default=None, max_length=4000)
    modified_tool_input: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class ApprovalResponse(BaseModel):
    id: str
    requested_by_user_id: str | None
    tool_name: str
    tool_input: dict[str, Any]
    status: ApprovalStatus
    reviewer_user_id: str | None
    decision_reason: str | None
    resumable_tool_call: dict[str, Any] | None
    created_at: datetime | None
    decided_at: datetime | None


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalResponse]


@router.post(
    "",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_approval(
    request: Annotated[ApprovalCreateRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> ApprovalResponse:
    payload = _approval_payload(
        tool_input=request.tool_input,
        reason=request.reason,
        risk_level=request.risk_level,
        categories=request.categories,
        actor_user_id=user.id,
        action="created",
    )
    approval = await create_approval_record(
        session,
        requested_by_user_id=user.id,
        tool_name=request.tool_name.strip(),
        tool_input=payload,
    )
    return _to_response(approval)


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    session: DbSession,
    _: CurrentUserDep,
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ApprovalListResponse:
    statement = select(Approval).order_by(Approval.created_at.desc()).limit(limit)
    if status_filter is not None:
        statement = statement.where(Approval.status == status_filter)
    result = await session.execute(statement)
    approvals = list(result.scalars().all())
    return ApprovalListResponse(approvals=[_to_response(approval) for approval in approvals])


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    session: DbSession,
    _: CurrentUserDep,
) -> ApprovalResponse:
    approval = await _get_approval(session, approval_id)
    return _to_response(approval)


@router.post("/{approval_id}/decision", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: str,
    request: Annotated[ApprovalDecisionRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> ApprovalResponse:
    _require_reviewer(user)
    approval = await _get_approval(session, approval_id)
    if approval.status != "pending":
        raise AppError("Approval has already been decided.", code="approval_already_decided")

    approval.status = request.decision
    approval.reviewer_user_id = user.id
    approval.decision_reason = request.decision_reason
    approval.decided_at = utc_now()
    approval.tool_input = _decision_payload(
        approval.tool_input,
        decision=request.decision,
        decision_reason=request.decision_reason,
        modified_tool_input=request.modified_tool_input,
        actor_user_id=user.id,
    )
    await session.commit()
    await session.refresh(approval)
    return _to_response(approval)


async def _get_approval(session: AsyncSession, approval_id: str) -> Approval:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise AppError("Approval not found.", code="approval_not_found", status_code=404)
    return approval


def _require_reviewer(user: CurrentUser) -> None:
    if user.role not in {"admin", "reviewer"}:
        raise AppError(
            "Only admin or reviewer can decide approvals.",
            code="approval_forbidden",
            status_code=403,
        )


def _approval_payload(
    *,
    tool_input: dict[str, Any],
    reason: str | None,
    risk_level: str,
    categories: list[str],
    actor_user_id: str,
    action: str,
) -> dict[str, Any]:
    return {
        "original_tool_input": tool_input,
        "approved_tool_input": None,
        "risk": {
            "reason": reason,
            "risk_level": risk_level,
            "categories": categories,
        },
        "audit": [_audit_event(action=action, actor_user_id=actor_user_id)],
    }


def _decision_payload(
    payload: dict[str, Any],
    *,
    decision: str,
    decision_reason: str | None,
    modified_tool_input: dict[str, Any] | None,
    actor_user_id: str,
) -> dict[str, Any]:
    result = dict(payload or {})
    original_tool_input = _tool_input_from_payload(result)
    result["approved_tool_input"] = (
        modified_tool_input if modified_tool_input is not None else original_tool_input
    )
    result["decision"] = {
        "status": decision,
        "reason": decision_reason,
    }
    audit = list(result.get("audit", []))
    audit.append(_audit_event(action=decision, actor_user_id=actor_user_id))
    result["audit"] = audit[-100:]
    return result


def _audit_event(*, action: str, actor_user_id: str) -> dict[str, str]:
    return {
        "action": action,
        "actor_user_id": actor_user_id,
        "created_at": utc_now().isoformat(),
    }


def _to_response(approval: Approval) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        requested_by_user_id=approval.requested_by_user_id,
        tool_name=approval.tool_name,
        tool_input=dict(approval.tool_input or {}),
        status=_approval_status(approval.status),
        reviewer_user_id=approval.reviewer_user_id,
        decision_reason=approval.decision_reason,
        resumable_tool_call=_resumable_tool_call(approval),
        created_at=approval.created_at,
        decided_at=approval.decided_at,
    )


def _resumable_tool_call(approval: Approval) -> dict[str, Any] | None:
    if approval.status != "approved":
        return None
    payload = dict(approval.tool_input or {})
    return {
        "name": approval.tool_name,
        "arguments": payload.get("approved_tool_input") or _tool_input_from_payload(payload),
    }


def _tool_input_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    original = payload.get("original_tool_input")
    if isinstance(original, dict):
        return original
    return dict(payload)


def _approval_status(value: str) -> ApprovalStatus:
    if value == "approved":
        return "approved"
    if value == "rejected":
        return "rejected"
    return "pending"
