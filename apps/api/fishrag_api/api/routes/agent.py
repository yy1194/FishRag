from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from fishrag_agent.approval import ApprovalCheck, default_approval_policy
from fishrag_agent.context import ContextItem
from fishrag_agent.memory import InMemoryMemoryStore
from fishrag_agent.runtime import AgentRunRequest, AgentRuntime, AgentToolCall
from fishrag_agent.skills import SkillRegistry, default_skill_registry
from fishrag_agent.subagents import (
    SubAgentRegistry,
    SubAgentRunner,
    default_subagent_registry,
)
from fishrag_common.config import Settings, get_settings
from fishrag_rag.embeddings import EmbeddingClient
from fishrag_rag.keyword_index import KeywordIndexClient
from fishrag_rag.rerankers import RerankerClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import (
    CurrentUser,
    get_current_user,
    get_embedding_client,
    get_keyword_index_client,
    get_reranker_client,
    get_session,
)
from fishrag_api.api.routes.planning import todo_store
from fishrag_api.api.routes.rag import (
    RagSearchRequest,
    _run_hybrid_search,
    _to_search_response,
)
from fishrag_api.core.errors import AppError
from fishrag_api.services.approvals import create_approval_record

router = APIRouter(prefix="/agent", tags=["agent"])

memory_store = InMemoryMemoryStore()
skill_registry = default_skill_registry()
subagent_registry = default_subagent_registry()

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbeddingClientDep = Annotated[EmbeddingClient, Depends(get_embedding_client)]
KeywordIndexClientDep = Annotated[KeywordIndexClient, Depends(get_keyword_index_client)]
RerankerClientDep = Annotated[RerankerClient, Depends(get_reranker_client)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


class AgentContextItemRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class AgentToolCallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class AgentRunBody(BaseModel):
    input: str = Field(min_length=1, max_length=12000)
    tool_calls: list[AgentToolCallRequest] = Field(default_factory=list, max_length=30)
    context_items: list[AgentContextItemRequest] = Field(default_factory=list, max_length=100)

    model_config = ConfigDict(extra="forbid")


class AgentCapabilitiesResponse(BaseModel):
    tools: list[str]
    subagents: list[dict[str, Any]]
    skills: list[dict[str, Any]]


class AgentRunResponse(BaseModel):
    run_id: str
    session_id: str
    status: str
    response: str
    tool_results: list[dict[str, Any]]
    context: dict[str, Any]
    available_tools: list[str]
    available_subagents: list[str]
    available_skills: list[str]


class ApiRagSearchTool:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        embedding_client: EmbeddingClient,
        keyword_index_client: KeywordIndexClient,
        reranker_client: RerankerClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embedding_client = embedding_client
        self.keyword_index_client = keyword_index_client
        self.reranker_client = reranker_client

    async def search(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        request = RagSearchRequest.model_validate(
            {
                "query": arguments.get("query"),
                "vector_limit": arguments.get("vector_limit", 20),
                "keyword_limit": arguments.get("keyword_limit", 20),
                "limit": arguments.get("limit", 10),
                "use_reranker": arguments.get("use_reranker", True),
                "reranker_top_n": arguments.get("reranker_top_n", 10),
            }
        )
        result = await _run_hybrid_search(
            request=request,
            session=self.session,
            settings=self.settings,
            embedding_client=self.embedding_client,
            keyword_index_client=self.keyword_index_client,
            reranker_client=self.reranker_client,
        )
        return _to_search_response(result).model_dump(mode="json")


class ApiApprovalHandler:
    def __init__(
        self,
        *,
        session: AsyncSession,
        user: CurrentUser,
    ) -> None:
        self.session = session
        self.user = user

    async def request_approval(
        self,
        *,
        session_id: str,
        user_input: str,
        tool_name: str,
        tool_arguments: Mapping[str, Any],
        check: ApprovalCheck,
    ) -> Mapping[str, Any]:
        approval = await create_approval_record(
            self.session,
            requested_by_user_id=self.user.id,
            tool_name=tool_name,
            tool_input={
                "session_id": session_id,
                "user_input": user_input,
                "original_tool_input": dict(tool_arguments),
                "approved_tool_input": None,
                "risk": check.as_dict(),
            },
        )
        return {
            "approval_id": approval.id,
            "approval_status": approval.status,
            "requested_by_user_id": approval.requested_by_user_id,
        }


@router.get("/tools", response_model=AgentCapabilitiesResponse)
async def get_agent_tools() -> AgentCapabilitiesResponse:
    runtime = _runtime(rag_search_tool=_StaticRagSearchTool())
    return _capabilities_response(runtime, skill_registry, subagent_registry)


@router.post("/sessions/{session_id}/run", response_model=AgentRunResponse)
async def run_agent(
    session_id: str,
    request: Annotated[AgentRunBody, Body()],
    session: DbSession,
    user: CurrentUserDep,
    settings: SettingsDep,
    embedding_client: EmbeddingClientDep,
    keyword_index_client: KeywordIndexClientDep,
    reranker_client: RerankerClientDep,
) -> AgentRunResponse:
    runtime = _runtime(
        rag_search_tool=ApiRagSearchTool(
            session=session,
            settings=settings,
            embedding_client=embedding_client,
            keyword_index_client=keyword_index_client,
            reranker_client=reranker_client,
        ),
        approval_handler=ApiApprovalHandler(session=session, user=user),
    )
    try:
        result = await runtime.run(
            AgentRunRequest(
                session_id=session_id,
                user_input=request.input,
                tool_calls=tuple(
                    AgentToolCall(name=call.name, arguments=call.arguments)
                    for call in request.tool_calls
                ),
                context_items=tuple(
                    ContextItem(
                        kind=item.kind,
                        content=item.content,
                        metadata=item.metadata,
                    )
                    for item in request.context_items
                ),
            )
        )
    except ValueError as exc:
        raise AppError(str(exc), code="agent_request_error") from exc
    return AgentRunResponse.model_validate(result.as_dict())


def _runtime(
    *,
    rag_search_tool: ApiRagSearchTool | _StaticRagSearchTool,
    approval_handler: ApiApprovalHandler | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        todo_store=todo_store,
        memory_store=memory_store,
        skill_registry=skill_registry,
        subagent_runner=SubAgentRunner(subagent_registry),
        rag_search_tool=rag_search_tool,
        approval_policy=default_approval_policy(),
        approval_handler=approval_handler,
    )


def _capabilities_response(
    runtime: AgentRuntime,
    skills: SkillRegistry,
    subagents: SubAgentRegistry,
) -> AgentCapabilitiesResponse:
    return AgentCapabilitiesResponse(
        tools=list(runtime.available_tools),
        subagents=[spec.as_dict() for spec in subagents.list_specs()],
        skills=[metadata.as_dict() for metadata in skills.list_metadata()],
    )


class _StaticRagSearchTool:
    async def search(self, _: Mapping[str, Any]) -> Mapping[str, Any]:
        raise ValueError("Static tool metadata only.")
