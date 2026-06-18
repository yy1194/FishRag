from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from fishrag_rag.retrieval import Citation, RagAnswer, RetrievalHit, no_evidence_answer


class ChatGenerationError(Exception):
    """Base exception for chat generation failures."""


class ChatConfigurationError(ChatGenerationError):
    """Raised when chat settings are incomplete."""


class ChatProviderError(ChatGenerationError):
    """Raised when chat provider returns an error."""


class ChatResponseError(ChatGenerationError):
    """Raised when chat response cannot be parsed."""


class ChatClient(Protocol):
    provider: str
    model: str

    async def complete(self, *, messages: Sequence[dict[str, str]]) -> str:
        """Return assistant text for messages."""


class OpenAICompatibleChatClient:
    provider: str
    model: str

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def complete(self, *, messages: Sequence[dict[str, str]]) -> str:
        if not self.base_url:
            raise ChatConfigurationError("Chat base URL is required.")
        if not self.api_key:
            raise ChatConfigurationError("Chat API key is required.")
        if not self.model:
            raise ChatConfigurationError("Chat model is required.")

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={"model": self.model, "messages": list(messages), "temperature": 0.2},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        if response.status_code >= 400:
            raise ChatProviderError(
                f"Chat provider returned HTTP {response.status_code}: {response.text}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ChatResponseError("Chat provider returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise ChatResponseError("Chat provider response must be a JSON object.")
        return _extract_chat_content(payload)


async def generate_rag_answer(
    *,
    query: str,
    hits: list[RetrievalHit],
    citations: list[Citation],
    chat_client: ChatClient,
) -> RagAnswer:
    if not hits:
        return no_evidence_answer(query)

    context = "\n\n".join(
        f"[C{index}] {hit.content}" for index, hit in enumerate(hits, start=1)
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是 FishRag 医学知识库助手。必须只基于给定证据回答，"
                "不要编造没有证据支持的医学事实。回答中需要引用 [C1] 这样的证据编号。"
            ),
        },
        {
            "role": "user",
            "content": f"问题：{query}\n\n证据：\n{context}",
        },
    ]
    answer = await chat_client.complete(messages=messages)
    return RagAnswer(query=query, answer=answer, citations=citations, is_answered=True)


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ChatResponseError("Chat response is missing choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise ChatResponseError("Chat choice must be an object.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ChatResponseError("Chat choice is missing message.")
    content = message.get("content")
    if not isinstance(content, str):
        raise ChatResponseError("Chat message content must be a string.")
    return content
