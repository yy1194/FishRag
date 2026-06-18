from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any

from fishrag_agent.planning import utc_now


@dataclass(frozen=True)
class MemoryItem:
    key: str
    value: str
    scope: str = "session"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "scope": self.scope,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class MemorySnapshot:
    session_id: str
    items: tuple[MemoryItem, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "items": [item.as_dict() for item in self.items],
        }


class InMemoryMemoryStore:
    """Thread-safe memory store used until database-backed memories are wired in."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items_by_session: dict[str, dict[tuple[str, str], MemoryItem]] = {}

    def remember(
        self,
        session_id: str,
        *,
        key: str,
        value: str,
        scope: str = "session",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        normalized_session_id = _normalize_text(session_id, "Session id")
        normalized_key = _normalize_text(key, "Memory key")
        normalized_value = _normalize_text(value, "Memory value")
        normalized_scope = _normalize_text(scope, "Memory scope")
        now = utc_now()

        with self._lock:
            session_items = self._items_by_session.setdefault(normalized_session_id, {})
            existing = session_items.get((normalized_scope, normalized_key))
            item = MemoryItem(
                key=normalized_key,
                value=normalized_value,
                scope=normalized_scope,
                metadata=metadata or {},
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            session_items[(normalized_scope, normalized_key)] = item
        return item

    def recall(
        self,
        session_id: str,
        *,
        scope: str | None = None,
        query: str | None = None,
    ) -> MemorySnapshot:
        normalized_session_id = _normalize_text(session_id, "Session id")
        query_text = query.strip().lower() if query else None
        scope_text = scope.strip() if scope else None

        with self._lock:
            items = tuple(self._items_by_session.get(normalized_session_id, {}).values())

        filtered: list[MemoryItem] = []
        for item in sorted(items, key=lambda memory: (memory.scope, memory.key)):
            if scope_text and item.scope != scope_text:
                continue
            if (
                query_text
                and query_text not in item.key.lower()
                and query_text not in item.value.lower()
            ):
                continue
            filtered.append(item)
        return MemorySnapshot(session_id=normalized_session_id, items=tuple(filtered))

    def clear(self, session_id: str) -> MemorySnapshot:
        normalized_session_id = _normalize_text(session_id, "Session id")
        with self._lock:
            self._items_by_session.pop(normalized_session_id, None)
        return MemorySnapshot(session_id=normalized_session_id, items=())


def _normalize_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} cannot be empty.")
    return normalized
