from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

TodoStatus = Literal["pending", "in_progress", "completed", "blocked", "cancelled"]
ALLOWED_STATUSES: set[str] = {"pending", "in_progress", "completed", "blocked", "cancelled"}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


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


def validate_todos(items: list[TodoItem]) -> list[TodoItem]:
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
