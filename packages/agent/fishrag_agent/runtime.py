from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast
from uuid import uuid4

from fishrag_agent.approval import ApprovalPolicy, ApprovalRequestHandler
from fishrag_agent.context import ContextItem, ContextSnapshot, compact_context, compress_payload
from fishrag_agent.memory import InMemoryMemoryStore
from fishrag_agent.planning import InMemoryTodoStore, TodoDraft, TodoStatus, write_todos
from fishrag_agent.skills import SkillRegistry
from fishrag_agent.subagents import SubAgentRunner, SubAgentTask


class RagSearchTool(Protocol):
    async def search(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Run a RAG search and return JSON-serializable data."""


@dataclass(frozen=True)
class AgentToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentToolResult:
    name: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "output": self.output,
            "error": self.error,
        }


@dataclass(frozen=True)
class AgentRunRequest:
    session_id: str
    user_input: str
    tool_calls: tuple[AgentToolCall, ...] = ()
    context_items: tuple[ContextItem, ...] = ()


@dataclass(frozen=True)
class AgentRunResult:
    run_id: str
    session_id: str
    status: str
    response: str
    tool_results: tuple[AgentToolResult, ...]
    context: ContextSnapshot
    available_tools: tuple[str, ...]
    available_subagents: tuple[str, ...]
    available_skills: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "response": self.response,
            "tool_results": [result.as_dict() for result in self.tool_results],
            "context": self.context.as_dict(),
            "available_tools": list(self.available_tools),
            "available_subagents": list(self.available_subagents),
            "available_skills": list(self.available_skills),
        }


class AgentRuntime:
    def __init__(
        self,
        *,
        todo_store: InMemoryTodoStore,
        memory_store: InMemoryMemoryStore,
        skill_registry: SkillRegistry,
        subagent_runner: SubAgentRunner,
        rag_search_tool: RagSearchTool | None = None,
        approval_policy: ApprovalPolicy | None = None,
        approval_handler: ApprovalRequestHandler | None = None,
        max_context_items: int = 12,
        max_context_chars: int = 6000,
        max_tool_output_chars: int = 4000,
    ) -> None:
        self.todo_store = todo_store
        self.memory_store = memory_store
        self.skill_registry = skill_registry
        self.subagent_runner = subagent_runner
        self.rag_search_tool = rag_search_tool
        self.approval_policy = approval_policy
        self.approval_handler = approval_handler
        self.max_context_items = max_context_items
        self.max_context_chars = max_context_chars
        self.max_tool_output_chars = max_tool_output_chars

    @property
    def available_tools(self) -> tuple[str, ...]:
        tools = [
            "write_todos",
            "remember",
            "recall_memory",
            "task",
            "list_skills",
            "load_skill",
        ]
        if self.rag_search_tool is not None:
            tools.append("rag_search")
        return tuple(tools)

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        session_id = _normalize_text(request.session_id, "Session id")
        user_input = _normalize_text(request.user_input, "User input")
        context_items = [
            *request.context_items,
            ContextItem(kind="user", content=user_input),
        ]
        tool_results: list[AgentToolResult] = []

        for call in request.tool_calls:
            result = await self._execute_tool(session_id, user_input, call)
            result = self._compress_tool_result(result)
            tool_results.append(result)
            context_items.append(
                ContextItem(
                    kind=f"tool:{call.name}",
                    content=str(result.output if result.status == "completed" else result.error),
                    metadata={"status": result.status},
                )
            )

        context = compact_context(
            context_items,
            max_items=self.max_context_items,
            max_chars=self.max_context_chars,
        )
        status = _run_status(tool_results)
        return AgentRunResult(
            run_id=str(uuid4()),
            session_id=session_id,
            status=status,
            response=_build_response(tool_results),
            tool_results=tuple(tool_results),
            context=context,
            available_tools=self.available_tools,
            available_subagents=tuple(self.subagent_runner.registry.list_names()),
            available_skills=tuple(skill.name for skill in self.skill_registry.list_metadata()),
        )

    async def _execute_tool(
        self,
        session_id: str,
        user_input: str,
        call: AgentToolCall,
    ) -> AgentToolResult:
        tool_name = call.name.strip()
        if self.approval_policy is not None:
            check = self.approval_policy.evaluate(
                tool_name=tool_name,
                arguments=call.arguments,
            )
            if check.requires_approval:
                output: dict[str, Any] = {"approval": check.as_dict()}
                if self.approval_handler is not None:
                    approval_result = await self.approval_handler.request_approval(
                        session_id=session_id,
                        user_input=user_input,
                        tool_name=tool_name,
                        tool_arguments=call.arguments,
                        check=check,
                    )
                    output.update(dict(approval_result))
                return AgentToolResult(
                    name=tool_name,
                    status="approval_required",
                    output=output,
                )

        if tool_name not in self.available_tools:
            return AgentToolResult(
                name=tool_name,
                status="failed",
                error=f"Unknown tool: {tool_name}",
            )

        try:
            if tool_name == "write_todos":
                return self._write_todos(session_id, call.arguments)
            if tool_name == "remember":
                return self._remember(session_id, call.arguments)
            if tool_name == "recall_memory":
                return self._recall_memory(session_id, call.arguments)
            if tool_name == "task":
                return await self._delegate_task(call.arguments)
            if tool_name == "list_skills":
                return self._list_skills()
            if tool_name == "load_skill":
                return self._load_skill(call.arguments)
            if tool_name == "rag_search":
                return await self._rag_search(call.arguments)
        except (KeyError, TypeError, ValueError) as exc:
            return AgentToolResult(name=tool_name, status="failed", error=str(exc))

        return AgentToolResult(
            name=tool_name,
            status="failed",
            error=f"Unsupported tool: {tool_name}",
        )

    def _write_todos(self, session_id: str, arguments: Mapping[str, Any]) -> AgentToolResult:
        raw_todos = _list_argument(arguments, "todos")
        drafts: list[TodoDraft] = []
        for item in raw_todos:
            if not isinstance(item, Mapping):
                raise ValueError("Each todo must be an object.")
            drafts.append(
                TodoDraft(
                    id=_string_argument(item, "id"),
                    content=_string_argument(item, "content"),
                    status=_todo_status_argument(item.get("status", "pending")),
                )
            )
        snapshot = write_todos(session_id, drafts, store=self.todo_store)
        return AgentToolResult(
            name="write_todos",
            status="completed",
            output=snapshot.as_dict(),
        )

    def _remember(self, session_id: str, arguments: Mapping[str, Any]) -> AgentToolResult:
        metadata = arguments.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object.")
        item = self.memory_store.remember(
            session_id,
            key=_string_argument(arguments, "key"),
            value=_string_argument(arguments, "value"),
            scope=str(arguments.get("scope", "session")),
            metadata=metadata,
        )
        return AgentToolResult(name="remember", status="completed", output=item.as_dict())

    def _recall_memory(self, session_id: str, arguments: Mapping[str, Any]) -> AgentToolResult:
        snapshot = self.memory_store.recall(
            session_id,
            scope=_optional_string_argument(arguments, "scope"),
            query=_optional_string_argument(arguments, "query"),
        )
        return AgentToolResult(name="recall_memory", status="completed", output=snapshot.as_dict())

    async def _delegate_task(self, arguments: Mapping[str, Any]) -> AgentToolResult:
        tasks = _task_arguments(arguments)
        results = await self.subagent_runner.delegate_many(tasks)
        return AgentToolResult(
            name="task",
            status="completed",
            output={"results": [result.as_dict() for result in results]},
        )

    def _list_skills(self) -> AgentToolResult:
        return AgentToolResult(
            name="list_skills",
            status="completed",
            output={"skills": [skill.as_dict() for skill in self.skill_registry.list_metadata()]},
        )

    def _load_skill(self, arguments: Mapping[str, Any]) -> AgentToolResult:
        package = self.skill_registry.load(_string_argument(arguments, "name"))
        return AgentToolResult(name="load_skill", status="completed", output=package.as_dict())

    async def _rag_search(self, arguments: Mapping[str, Any]) -> AgentToolResult:
        if self.rag_search_tool is None:
            raise ValueError("rag_search tool is not configured.")
        output = await self.rag_search_tool.search(arguments)
        return AgentToolResult(name="rag_search", status="completed", output=dict(output))

    def _compress_tool_result(self, result: AgentToolResult) -> AgentToolResult:
        if result.status != "completed":
            return result
        return AgentToolResult(
            name=result.name,
            status=result.status,
            output=compress_payload(result.output, max_chars=self.max_tool_output_chars),
            error=result.error,
        )


def _task_arguments(arguments: Mapping[str, Any]) -> list[SubAgentTask]:
    raw_tasks = arguments.get("tasks")
    if raw_tasks is not None:
        if not isinstance(raw_tasks, list):
            raise ValueError("tasks must be a list.")
        tasks: list[SubAgentTask] = []
        for item in raw_tasks:
            if not isinstance(item, Mapping):
                raise ValueError("Each delegated task must be an object.")
            tasks.append(_single_task_argument(item))
        return tasks
    return [_single_task_argument(arguments)]


def _single_task_argument(arguments: Mapping[str, Any]) -> SubAgentTask:
    return SubAgentTask(
        subagent=_string_argument(arguments, "subagent"),
        description=_string_argument(arguments, "description"),
        input=str(arguments.get("input", "")),
    )


def _string_argument(arguments: Mapping[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string.")
    return value.strip()


def _optional_string_argument(arguments: Mapping[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string.")
    normalized = value.strip()
    return normalized or None


def _list_argument(arguments: Mapping[str, Any], key: str) -> list[Any]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list.")
    return value


def _todo_status_argument(value: Any) -> TodoStatus:
    if value not in {"pending", "in_progress", "completed", "blocked", "cancelled"}:
        raise ValueError(f"Unsupported todo status: {value}")
    return cast(TodoStatus, value)


def _normalize_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} cannot be empty.")
    return normalized


def _build_response(tool_results: Sequence[AgentToolResult]) -> str:
    if not tool_results:
        return "已记录用户输入，等待下一步工具调用。"
    approvals = sum(1 for result in tool_results if result.status == "approval_required")
    if approvals:
        return f"已暂停 {approvals} 个高风险工具调用，等待人工审批。"
    completed = sum(1 for result in tool_results if result.status == "completed")
    failed = len(tool_results) - completed
    if failed:
        return f"已执行 {len(tool_results)} 个工具调用，其中 {failed} 个失败。"
    return f"已执行 {completed} 个工具调用。"


def _run_status(tool_results: Sequence[AgentToolResult]) -> str:
    if any(result.status == "approval_required" for result in tool_results):
        return "waiting_for_approval"
    if all(result.status == "completed" for result in tool_results):
        return "completed"
    return "failed"
