from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest
from fishrag_rag.generation import (
    ChatConfigurationError,
    OpenAICompatibleChatClient,
    generate_rag_answer,
)
from fishrag_rag.retrieval import RetrievalHit, build_citations


class FakeChatClient:
    provider = "fake"
    model = "fake-chat"

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def complete(self, *, messages: Sequence[dict[str, str]]) -> str:
        self.messages = list(messages)
        return "Answer based on evidence [C1]."


@pytest.mark.asyncio
async def test_openai_compatible_chat_client_extracts_message_content() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "chat answer"}}]},
        )

    client = OpenAICompatibleChatClient(
        provider="test",
        base_url="https://chat.example/v1",
        api_key="secret",
        model="chat-model",
        transport=httpx.MockTransport(handler),
    )

    result = await client.complete(messages=[{"role": "user", "content": "hello"}])

    assert result == "chat answer"
    assert str(requests[0].url) == "https://chat.example/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_chat_client_retries_retryable_provider_errors() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"choices": [{"message": {"content": "recovered"}}]})

    client = OpenAICompatibleChatClient(
        provider="test",
        base_url="https://chat.example/v1",
        api_key="secret",
        model="chat-model",
        max_attempts=2,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    result = await client.complete(messages=[{"role": "user", "content": "hello"}])

    assert result == "recovered"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_chat_client_rejects_missing_api_key() -> None:
    client = OpenAICompatibleChatClient(
        provider="test",
        base_url="https://chat.example/v1",
        api_key="",
        model="chat-model",
    )

    with pytest.raises(ChatConfigurationError):
        await client.complete(messages=[{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_generate_rag_answer_uses_citation_context() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-1",
        document_id="doc-1",
        chunk_index=0,
        content="evidence text",
        score=0.8,
        source="hybrid",
    )
    chat_client = FakeChatClient()

    answer = await generate_rag_answer(
        query="question",
        hits=[hit],
        citations=build_citations([hit]),
        chat_client=chat_client,
    )

    assert answer.is_answered
    assert answer.answer == "Answer based on evidence [C1]."
    assert "[C1] evidence text" in chat_client.messages[1]["content"]
