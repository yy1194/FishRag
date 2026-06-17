from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Literal, TypeVar

TodoStatus = Literal["pending", "in_progress", "completed", "blocked", "cancelled"]
ALLOWED_STATUSES: set[str] = {"pending", "in_progress", "completed", "blocked", "cancelled"}
TodoT = TypeVar("TodoT", "TodoItem", "TodoDraft")


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class TodoDraft:
    id: str
    content: str
    status: TodoStatus = "pending"


@dataclass(frozen=True)
class TodoItem:
    id: str
    content: str
    status: TodoStatus = "pending"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class TodoStats:
    total: int
    pending: int
    in_progress: int
    completed: int
    blocked: int
    cancelled: int

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "pending": self.pending,
            "in_progress": self.in_progress,
            "completed": self.completed,
            "blocked": self.blocked,
            "cancelled": self.cancelled,
        }


@dataclass(frozen=True)
class TodoSnapshot:
    session_id: str
    items: tuple[TodoItem, ...]
    updated_at: datetime

    @property
    def stats(self) -> TodoStats:
        counts = {status: 0 for status in ALLOWED_STATUSES}
        for item in self.items:
            counts[item.status] += 1
        return TodoStats(
            total=len(self.items),
            pending=counts["pending"],
            in_progress=counts["in_progress"],
            completed=counts["completed"],
            blocked=counts["blocked"],
            cancelled=counts["cancelled"],
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "todos": [item.as_dict() for item in self.items],
            "stats": self.stats.as_dict(),
            "updated_at": self.updated_at.isoformat(),
        }


def validate_todos(items: list[TodoT]) -> list[TodoT]:
    seen: set[str] = set()
    for item in items:
        if not item.id.strip():
            raise ValueError("Todo id cannot be empty.")
        if item.id in seen:
            raise ValueError(f"Duplicate todo id: {item.id}")
        if not item.content.strip():
            raise ValueError(f"Todo content cannot be empty: {item.id}")
        if item.status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported todo status: {item.status}")
        seen.add(item.id)
    return items


def normalize_session_id(session_id: str) -> str:
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("Session id cannot be empty.")
    return normalized


@dataclass
class TodoList:
    items: list[TodoItem] = field(default_factory=list)

    def replace(self, items: list[TodoItem]) -> None:
        self.items = validate_todos(items)

    def upsert(self, item: TodoItem) -> None:
        validate_todos([item])
        remaining = [existing for existing in self.items if existing.id != item.id]
        self.items = validate_todos([*remaining, item])

    def as_dict(self) -> list[dict[str, str]]:
        return [item.as_dict() for item in self.items]


class InMemoryTodoStore:
    """Thread-safe in-memory store used until database persistence is wired in."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items_by_session: dict[str, tuple[TodoItem, ...]] = {}

    def get(self, session_id: str) -> TodoSnapshot:
        normalized_session_id = normalize_session_id(session_id)
        with self._lock:
            items = self._items_by_session.get(normalized_session_id, ())
        return TodoSnapshot(
            session_id=normalized_session_id,
            items=items,
            updated_at=_snapshot_updated_at(items),
        )

    def write(self, session_id: str, drafts: list[TodoDraft]) -> TodoSnapshot:
        normalized_session_id = normalize_session_id(session_id)
        validate_todos(drafts)
        now = utc_now()

        with self._lock:
            existing = {
                item.id: item for item in self._items_by_session.get(normalized_session_id, ())
            }
            items = tuple(_merge_todo(existing.get(draft.id), draft, now) for draft in drafts)
            self._items_by_session[normalized_session_id] = items

        return TodoSnapshot(session_id=normalized_session_id, items=items, updated_at=now)

    def clear(self, session_id: str) -> TodoSnapshot:
        normalized_session_id = normalize_session_id(session_id)
        with self._lock:
            self._items_by_session.pop(normalized_session_id, None)
        return TodoSnapshot(session_id=normalized_session_id, items=(), updated_at=utc_now())


def _merge_todo(existing: TodoItem | None, draft: TodoDraft, now: datetime) -> TodoItem:
    if existing is None:
        return TodoItem(
            id=draft.id.strip(),
            content=draft.content.strip(),
            status=draft.status,
            created_at=now,
            updated_at=now,
        )

    content = draft.content.strip()
    has_changed = existing.content != content or existing.status != draft.status
    return TodoItem(
        id=existing.id,
        content=content,
        status=draft.status,
        created_at=existing.created_at,
        updated_at=now if has_changed else existing.updated_at,
    )


def _snapshot_updated_at(items: tuple[TodoItem, ...]) -> datetime:
    if not items:
        return utc_now()
    return max(item.updated_at for item in items)


def write_todos(
    session_id: str,
    todos: list[TodoDraft],
    *,
    store: InMemoryTodoStore,
) -> TodoSnapshot:
    return store.write(session_id, todos)
