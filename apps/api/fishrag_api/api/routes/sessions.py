from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import CurrentUser, get_current_user, get_session
from fishrag_api.core.errors import AppError
from fishrag_api.db.models import ChatSession, Message, utc_now

router = APIRouter(prefix="/sessions", tags=["sessions"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
SessionStatus = Literal["active", "archived", "deleted"]
MessageRole = Literal["system", "user", "assistant", "tool"]


class ChatSessionCreateRequest(BaseModel):
    title: str = Field(default="新的会话", min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=12000)

    model_config = ConfigDict(extra="forbid")


class ChatSessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: SessionStatus | None = None
    summary: str | None = Field(default=None, max_length=12000)

    model_config = ConfigDict(extra="forbid")


class ChatSessionSummaryRequest(BaseModel):
    max_messages: int = Field(default=20, ge=1, le=200)
    max_chars: int = Field(default=1200, ge=100, le=12000)

    model_config = ConfigDict(extra="forbid")


class MessageCreateRequest(BaseModel):
    role: MessageRole
    content: str = Field(min_length=1, max_length=120000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: MessageRole
    content: str
    metadata: dict[str, Any]
    created_at: datetime | None


class ChatSessionResponse(BaseModel):
    id: str
    user_id: str
    title: str
    status: SessionStatus
    summary: str | None
    created_at: datetime | None
    updated_at: datetime | None


class ChatSessionDetailResponse(ChatSessionResponse):
    messages: list[MessageResponse] = Field(default_factory=list)


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse]


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]


@router.post(
    "",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    request: Annotated[ChatSessionCreateRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> ChatSessionResponse:
    chat_session = ChatSession(
        user_id=user.id,
        title=request.title.strip(),
        status="active",
        summary=request.summary,
    )
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)
    return _to_session_response(chat_session)


@router.get("", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    session: DbSession,
    user: CurrentUserDep,
    status_filter: Annotated[SessionStatus | None, Query(alias="status")] = None,
    include_deleted: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ChatSessionListResponse:
    statement = (
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
    )
    if status_filter is not None:
        statement = statement.where(ChatSession.status == status_filter)
    elif not include_deleted:
        statement = statement.where(ChatSession.status != "deleted")

    result = await session.execute(statement)
    sessions = list(result.scalars().all())
    return ChatSessionListResponse(
        sessions=[_to_session_response(chat_session) for chat_session in sessions]
    )


@router.get("/{session_id}", response_model=ChatSessionDetailResponse)
async def get_chat_session(
    session_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> ChatSessionDetailResponse:
    chat_session = await _get_owned_session(session, user, session_id)
    messages = await _load_messages(session, chat_session.id)
    return ChatSessionDetailResponse(
        **_to_session_response(chat_session).model_dump(),
        messages=[_to_message_response(message) for message in messages],
    )


@router.patch("/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: str,
    request: Annotated[ChatSessionUpdateRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> ChatSessionResponse:
    chat_session = await _get_owned_session(session, user, session_id)
    if request.title is not None:
        chat_session.title = request.title.strip()
    if request.status is not None:
        chat_session.status = request.status
    if request.summary is not None:
        chat_session.summary = request.summary
    chat_session.updated_at = utc_now()
    await session.commit()
    await session.refresh(chat_session)
    return _to_session_response(chat_session)


@router.delete("/{session_id}", response_model=ChatSessionResponse)
async def delete_chat_session(
    session_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> ChatSessionResponse:
    chat_session = await _get_owned_session(session, user, session_id)
    chat_session.status = "deleted"
    chat_session.updated_at = utc_now()
    await session.commit()
    await session.refresh(chat_session)
    return _to_session_response(chat_session)


@router.post("/{session_id}/restore", response_model=ChatSessionResponse)
async def restore_chat_session(
    session_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> ChatSessionResponse:
    chat_session = await _get_owned_session(session, user, session_id)
    chat_session.status = "active"
    chat_session.updated_at = utc_now()
    await session.commit()
    await session.refresh(chat_session)
    return _to_session_response(chat_session)


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def list_messages(
    session_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> MessageListResponse:
    chat_session = await _get_owned_session(session, user, session_id)
    messages = await _load_messages(session, chat_session.id)
    return MessageListResponse(messages=[_to_message_response(message) for message in messages])


@router.post(
    "/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def append_message(
    session_id: str,
    request: Annotated[MessageCreateRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> MessageResponse:
    chat_session = await _get_owned_session(session, user, session_id)
    if chat_session.status == "deleted":
        raise AppError("Cannot append messages to a deleted session.", code="session_deleted")
    message = Message(
        session_id=chat_session.id,
        role=request.role,
        content=request.content,
        metadata_=request.metadata,
    )
    chat_session.updated_at = utc_now()
    session.add(message)
    await session.commit()
    await session.refresh(message)
    await session.refresh(chat_session)
    return _to_message_response(message)


@router.post("/{session_id}/summary", response_model=ChatSessionResponse)
async def generate_session_summary(
    session_id: str,
    request: Annotated[ChatSessionSummaryRequest, Body()],
    session: DbSession,
    user: CurrentUserDep,
) -> ChatSessionResponse:
    chat_session = await _get_owned_session(session, user, session_id)
    messages = await _load_messages(session, chat_session.id)
    chat_session.summary = _build_summary(
        messages[-request.max_messages :],
        max_chars=request.max_chars,
    )
    chat_session.updated_at = utc_now()
    await session.commit()
    await session.refresh(chat_session)
    return _to_session_response(chat_session)


async def _get_owned_session(
    session: AsyncSession,
    user: CurrentUser,
    session_id: str,
) -> ChatSession:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None or chat_session.user_id != user.id:
        raise AppError("Chat session not found.", code="chat_session_not_found", status_code=404)
    return chat_session


async def _load_messages(session: AsyncSession, session_id: str) -> list[Message]:
    result = await session.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    )
    return list(result.scalars().all())


def _build_summary(messages: list[Message], *, max_chars: int) -> str:
    if not messages:
        return "当前会话暂无消息。"
    lines: list[str] = []
    for message in messages:
        content = message.content.replace("\n", " ").strip()
        if len(content) > 220:
            content = f"{content[:217]}..."
        lines.append(f"{message.role}: {content}")
    summary = "\n".join(lines)
    if len(summary) <= max_chars:
        return summary
    return f"{summary[: max_chars - 3]}..."


def _to_session_response(chat_session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=chat_session.id,
        user_id=chat_session.user_id,
        title=chat_session.title,
        status=_session_status(chat_session.status),
        summary=chat_session.summary,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


def _to_message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=_message_role(message.role),
        content=message.content,
        metadata=dict(message.metadata_ or {}),
        created_at=message.created_at,
    )


def _session_status(value: str) -> SessionStatus:
    if value == "archived":
        return "archived"
    if value == "deleted":
        return "deleted"
    return "active"


def _message_role(value: str) -> MessageRole:
    if value == "system":
        return "system"
    if value == "assistant":
        return "assistant"
    if value == "tool":
        return "tool"
    return "user"
