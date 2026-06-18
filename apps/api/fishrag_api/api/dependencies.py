from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fishrag_common.config import get_settings
from fishrag_rag.embeddings import EmbeddingClient, OpenAICompatibleEmbeddingClient
from fishrag_rag.generation import ChatClient, OpenAICompatibleChatClient
from fishrag_rag.keyword_index import KeywordIndexClient, OpenSearchKeywordIndexClient
from fishrag_rag.rerankers import OpenAICompatibleRerankerClient, RerankerClient
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.core.security import TokenPayload, decode_access_token
from fishrag_api.db.session import get_db_session


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: str


async def get_session() -> AsyncIterator[AsyncSession]:
    async for session in get_db_session():
        yield session


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload: TokenPayload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return CurrentUser(id=payload.subject, role=payload.role)


def require_roles(*allowed_roles: str) -> Callable[[CurrentUser], CurrentUser]:
    def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role permissions.",
            )
        return user

    return dependency


def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    return OpenAICompatibleEmbeddingClient(
        provider=settings.embedding_provider,
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        expected_dimensions=settings.embedding_dimensions,
    )


def get_keyword_index_client() -> KeywordIndexClient:
    settings = get_settings()
    return OpenSearchKeywordIndexClient(
        base_url=settings.opensearch_url,
        index_name=settings.opensearch_index_name,
    )


def get_reranker_client() -> RerankerClient:
    settings = get_settings()
    return OpenAICompatibleRerankerClient(
        provider=settings.reranker_provider,
        base_url=settings.reranker_base_url,
        api_key=settings.reranker_api_key,
        model=settings.reranker_model,
    )


def get_chat_client() -> ChatClient:
    settings = get_settings()
    return OpenAICompatibleChatClient(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.chat_model,
    )
