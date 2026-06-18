from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fishrag_agent.context import ContextItem
from fishrag_agent.memory import InMemoryMemoryStore
from fishrag_agent.planning import InMemoryTodoStore
from fishrag_agent.runtime import AgentRunRequest, AgentRuntime, AgentToolCall
from fishrag_agent.skills import default_skill_registry
from fishrag_agent.subagents import SubAgentRunner, default_subagent_registry


class FakeRagSearchTool:
    async def search(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "query": arguments["query"],
            "hits": [{"chunk_id": "chunk-1", "content": "evidence"}],
            "citations": [{"id": "C1", "chunk_id": "chunk-1"}],
        }


def _runtime() -> AgentRuntime:
    return AgentRuntime(
        todo_store=InMemoryTodoStore(),
        memory_store=InMemoryMemoryStore(),
        skill_registry=default_skill_registry(),
        subagent_runner=SubAgentRunner(default_subagent_registry()),
        rag_search_tool=FakeRagSearchTool(),
        max_context_items=3,
        max_context_chars=400,
    )


@pytest.mark.asyncio
async def test_agent_runtime_runs_core_tools_and_compacts_context() -> None:
    runtime = _runtime()

    result = await runtime.run(
        AgentRunRequest(
            session_id="session-1",
            user_input="请完成阶段 4",
            context_items=tuple(
                ContextItem(kind="history", content=f"old context {index}" * 20)
                for index in range(5)
            ),
            tool_calls=(
                AgentToolCall(
                    name="write_todos",
                    arguments={
                        "todos": [
                            {"id": "1", "content": "实现 Agent 运行时", "status": "completed"},
                            {"id": "2", "content": "补测试", "status": "in_progress"},
                        ]
                    },
                ),
                AgentToolCall(
                    name="remember",
                    arguments={"key": "stage", "value": "4", "scope": "session"},
                ),
                AgentToolCall(name="recall_memory", arguments={"query": "stage"}),
                AgentToolCall(name="load_skill", arguments={"name": "rag_answering"}),
                AgentToolCall(
                    name="task",
                    arguments={
                        "tasks": [
                            {
                                "subagent": "rag_researcher",
                                "description": "整理检索证据",
                                "input": "question",
                            },
                            {
                                "subagent": "medical_reviewer",
                                "description": "审核医学风险",
                            },
                        ]
                    },
                ),
                AgentToolCall(
                    name="rag_search",
                    arguments={"query": "高血压", "limit": 1},
                ),
            ),
        )
    )

    assert result.status == "completed"
    assert result.response == "已执行 6 个工具调用。"
    assert [tool.name for tool in result.tool_results] == [
        "write_todos",
        "remember",
        "recall_memory",
        "load_skill",
        "task",
        "rag_search",
    ]
    assert result.tool_results[0].output["stats"]["total"] == 2
    assert result.tool_results[2].output["items"][0]["key"] == "stage"
    assert result.tool_results[3].output["metadata"]["name"] == "rag_answering"
    assert len(result.tool_results[4].output["results"]) == 2
    assert result.tool_results[5].output["citations"][0]["id"] == "C1"
    assert result.context.compressed
    assert "rag_search" in result.available_tools
    assert "rag_researcher" in result.available_subagents
    assert "task_planning" in result.available_skills


@pytest.mark.asyncio
async def test_agent_runtime_reports_unknown_tool_without_crashing() -> None:
    runtime = _runtime()

    result = await runtime.run(
        AgentRunRequest(
            session_id="session-unknown",
            user_input="hello",
            tool_calls=(AgentToolCall(name="missing_tool"),),
        )
    )

    assert result.status == "failed"
    assert result.tool_results[0].status == "failed"
    assert result.tool_results[0].error == "Unknown tool: missing_tool"
