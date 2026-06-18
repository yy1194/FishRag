from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fishrag_agent.approval import (
    ApprovalCheck,
    ApprovalRequestHandler,
    apply_medical_safety_guard,
    assess_medical_safety,
    default_approval_policy,
)
from fishrag_agent.memory import InMemoryMemoryStore
from fishrag_agent.planning import InMemoryTodoStore
from fishrag_agent.runtime import AgentRunRequest, AgentRuntime, AgentToolCall
from fishrag_agent.skills import default_skill_registry
from fishrag_agent.subagents import SubAgentRunner, default_subagent_registry


class FakeApprovalHandler:
    async def request_approval(
        self,
        *,
        session_id: str,
        user_input: str,
        tool_name: str,
        tool_arguments: Mapping[str, Any],
        check: ApprovalCheck,
    ) -> Mapping[str, Any]:
        return {
            "approval_id": "approval-1",
            "session_id": session_id,
            "tool_name": tool_name,
            "risk": check.as_dict(),
        }


def test_default_approval_policy_marks_destructive_tools_as_high_risk() -> None:
    check = default_approval_policy().evaluate(
        tool_name="delete_document",
        arguments={"document_id": "doc-1"},
    )

    assert check.requires_approval
    assert check.risk_level == "high"
    assert "knowledge_base_mutation" in check.categories


@pytest.mark.asyncio
async def test_agent_runtime_interrupts_high_risk_tool_for_approval() -> None:
    handler: ApprovalRequestHandler = FakeApprovalHandler()
    runtime = AgentRuntime(
        todo_store=InMemoryTodoStore(),
        memory_store=InMemoryMemoryStore(),
        skill_registry=default_skill_registry(),
        subagent_runner=SubAgentRunner(default_subagent_registry()),
        approval_policy=default_approval_policy(),
        approval_handler=handler,
    )

    result = await runtime.run(
        AgentRunRequest(
            session_id="session-1",
            user_input="删除这份文档",
            tool_calls=(
                AgentToolCall(
                    name="delete_document",
                    arguments={"document_id": "doc-1"},
                ),
            ),
        )
    )

    assert result.status == "waiting_for_approval"
    assert result.tool_results[0].status == "approval_required"
    assert result.tool_results[0].output["approval_id"] == "approval-1"


def test_medical_safety_guard_blocks_high_risk_answer_without_citations() -> None:
    guarded = apply_medical_safety_guard(
        query="这个药应该用多少剂量？",
        answer="建议立即调整剂量。",
        citation_count=0,
    )

    assert not guarded.is_answered
    assert guarded.assessment.high_risk
    assert guarded.assessment.blocked
    assert "已拦截" in guarded.answer


def test_medical_safety_guard_adds_disclaimer_when_citations_exist() -> None:
    assessment = assess_medical_safety(
        query="手术后如何停药？",
        answer="资料提示需要遵医嘱调整。",
        citation_count=1,
    )
    guarded = apply_medical_safety_guard(
        query="手术后如何停药？",
        answer="资料提示需要遵医嘱调整。[C1]",
        citation_count=1,
    )

    assert assessment.high_risk
    assert not assessment.blocked
    assert guarded.is_answered
    assert "不能替代医生诊断" in guarded.answer
