from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContextItem:
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "content": self.content,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ContextSnapshot:
    items: tuple[ContextItem, ...]
    summary: str | None
    token_estimate: int
    compressed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in self.items],
            "summary": self.summary,
            "token_estimate": self.token_estimate,
            "compressed": self.compressed,
        }


def estimate_context_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def compact_context(
    items: Sequence[ContextItem],
    *,
    max_items: int = 12,
    max_chars: int = 6000,
    summary_chars: int = 1200,
) -> ContextSnapshot:
    normalized_items = tuple(
        item for item in items if item.kind.strip() and item.content.strip()
    )
    total_chars = sum(len(item.content) for item in normalized_items)
    if len(normalized_items) <= max_items and total_chars <= max_chars:
        return ContextSnapshot(
            items=normalized_items,
            summary=None,
            token_estimate=sum(estimate_context_tokens(item.content) for item in normalized_items),
            compressed=False,
        )

    recent_items = normalized_items[-max_items:]
    older_items = normalized_items[: max(0, len(normalized_items) - len(recent_items))]
    while sum(len(item.content) for item in recent_items) > max_chars and len(recent_items) > 1:
        older_items = (*older_items, recent_items[0])
        recent_items = recent_items[1:]

    summary = summarize_context_items(older_items, max_chars=summary_chars)
    token_estimate = sum(estimate_context_tokens(item.content) for item in recent_items)
    if summary:
        token_estimate += estimate_context_tokens(summary)
    return ContextSnapshot(
        items=tuple(recent_items),
        summary=summary,
        token_estimate=token_estimate,
        compressed=True,
    )


def summarize_context_items(
    items: Sequence[ContextItem],
    *,
    max_chars: int = 1200,
) -> str | None:
    if not items:
        return None

    lines: list[str] = []
    for item in items:
        content = item.content.replace("\n", " ").strip()
        if len(content) > 220:
            content = f"{content[:217]}..."
        lines.append(f"- {item.kind}: {content}")
    summary = "\n".join(lines)
    if len(summary) <= max_chars:
        return summary
    return f"{summary[: max_chars - 3]}..."


def compress_payload(
    payload: Mapping[str, Any],
    *,
    max_chars: int = 4000,
) -> dict[str, Any]:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(rendered) <= max_chars:
        return dict(payload)
    return {
        "compressed": True,
        "original_chars": len(rendered),
        "preview": rendered[:max_chars],
    }
