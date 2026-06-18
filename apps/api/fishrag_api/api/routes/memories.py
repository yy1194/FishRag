from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import CurrentUser, get_current_user, get_session
from fishrag_api.core.errors import AppError
from fishrag_api.db.models import Memory, utc_now

router = APIRouter(prefix="/memories", tags=["memories"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


class MemoryCreateRequest(BaseModel):
    scope: str = Field(default="profile", min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1, max_length=120000)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class MemoryUpdateRequest(BaseModel):
    scope: str | None = Field(default=None, min_length=1, max_length=64)
    key: str | None = Field(default=None, min_length=1, max_length=255)
    value: str | None = Field(default=None, min_length=1, max_length=120000)
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class MemoryResponse(BaseModel):
    id: str
    user_id: str
    scope: str
    key: str
    value: str
    enabled: bool
    metadata: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None


class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]


@router.post(
    "",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_memory(
    request: Annotated[MemoryCreateRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> MemoryResponse:
    metadata = _memory_metadata(
        request.metadata,
        enabled=request.enabled,
        action="created",
        actor_user_id=user.id,
    )
    memory = Memory(
        user_id=user.id,
        scope=request.scope.strip(),
        key=request.key.strip(),
        value=request.value.strip(),
        metadata_=metadata,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return _to_memory_response(memory)


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    session: DbSession,
    user: CurrentUserDep,
    scope: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    query: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    enabled_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> MemoryListResponse:
    statement = (
        select(Memory)
        .where(Memory.user_id == user.id)
        .order_by(Memory.updated_at.desc())
        .limit(limit)
    )
    if scope is not None:
        statement = statement.where(Memory.scope == scope.strip())

    result = await session.execute(statement)
    memories = list(result.scalars().all())
    filtered = [
        memory
        for memory in memories
        if _memory_matches(memory, query=query, enabled_only=enabled_only)
    ]
    return MemoryListResponse(memories=[_to_memory_response(memory) for memory in filtered])


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> MemoryResponse:
    memory = await _get_owned_memory(session, user, memory_id)
    return _to_memory_response(memory)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    request: Annotated[MemoryUpdateRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> MemoryResponse:
    memory = await _get_owned_memory(session, user, memory_id)
    if request.scope is not None:
        memory.scope = request.scope.strip()
    if request.key is not None:
        memory.key = request.key.strip()
    if request.value is not None:
        memory.value = request.value.strip()

    metadata = dict(memory.metadata_ or {})
    if request.metadata is not None:
        metadata.update(request.metadata)
    enabled = _memory_enabled(memory) if request.enabled is None else request.enabled
    memory.metadata_ = _memory_metadata(
        metadata,
        enabled=enabled,
        action="updated",
        actor_user_id=user.id,
    )
    memory.updated_at = utc_now()
    await session.commit()
    await session.refresh(memory)
    return _to_memory_response(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> None:
    memory = await _get_owned_memory(session, user, memory_id)
    await session.delete(memory)
    await session.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memories_by_scope(
    session: DbSession,
    user: CurrentUserDep,
    scope: Annotated[str, Query(min_length=1, max_length=64)],
) -> None:
    await session.execute(delete(Memory).where(Memory.user_id == user.id, Memory.scope == scope))
    await session.commit()


async def _get_owned_memory(
    session: AsyncSession,
    user: CurrentUser,
    memory_id: str,
) -> Memory:
    memory = await session.get(Memory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise AppError("Memory not found.", code="memory_not_found", status_code=404)
    return memory


def _memory_matches(
    memory: Memory,
    *,
    query: str | None,
    enabled_only: bool,
) -> bool:
    if enabled_only and not _memory_enabled(memory):
        return False
    if query is None:
        return True
    normalized_query = query.strip().lower()
    return normalized_query in memory.key.lower() or normalized_query in memory.value.lower()


def _memory_enabled(memory: Memory) -> bool:
    metadata = dict(memory.metadata_ or {})
    enabled = metadata.get("enabled", True)
    return bool(enabled)


def _memory_metadata(
    metadata: dict[str, Any],
    *,
    enabled: bool,
    action: str,
    actor_user_id: str,
) -> dict[str, Any]:
    result = dict(metadata)
    result["enabled"] = enabled
    audit = list(result.get("audit", []))
    audit.append(
        {
            "action": action,
            "actor_user_id": actor_user_id,
            "created_at": utc_now().isoformat(),
        }
    )
    result["audit"] = audit[-50:]
    return result


def _to_memory_response(memory: Memory) -> MemoryResponse:
    metadata = dict(memory.metadata_ or {})
    return MemoryResponse(
        id=memory.id,
        user_id=memory.user_id,
        scope=memory.scope,
        key=memory.key,
        value=memory.value,
        enabled=bool(metadata.get("enabled", True)),
        metadata=metadata,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )
