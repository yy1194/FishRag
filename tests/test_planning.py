from __future__ import annotations

import pytest
from fishrag_agent.planning import (
    InMemoryTodoStore,
    TodoDraft,
    TodoItem,
    TodoList,
    validate_todos,
    write_todos,
)


def test_todo_list_upsert_replaces_existing_item() -> None:
    todo_list = TodoList()
    todo_list.upsert(TodoItem(id="1", content="初始化项目", status="pending"))
    todo_list.upsert(TodoItem(id="1", content="初始化项目", status="completed"))

    assert len(todo_list.items) == 1
    assert todo_list.items[0].status == "completed"


def test_validate_todos_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError):
        validate_todos(
            [
                TodoItem(id="1", content="A"),
                TodoItem(id="1", content="B"),
            ]
        )


def test_write_todos_tracks_stats_and_preserves_created_at() -> None:
    store = InMemoryTodoStore()

    first = write_todos(
        "session-a",
        [
            TodoDraft(id="1", content="读取需求", status="completed"),
            TodoDraft(id="2", content="实现 Planning", status="in_progress"),
        ],
        store=store,
    )
    second = write_todos(
        "session-a",
        [
            TodoDraft(id="1", content="读取需求", status="completed"),
            TodoDraft(id="2", content="实现 Planning API", status="completed"),
            TodoDraft(id="3", content="补测试", status="pending"),
        ],
        store=store,
    )

    assert second.session_id == "session-a"
    assert second.stats.completed == 2
    assert second.stats.pending == 1
    assert second.items[0].created_at == first.items[0].created_at
    assert second.items[0].updated_at == first.items[0].updated_at
    assert second.items[1].created_at == first.items[1].created_at
    assert second.items[1].updated_at >= first.items[1].updated_at


def test_write_todos_rejects_blank_session_id() -> None:
    store = InMemoryTodoStore()

    with pytest.raises(ValueError):
        write_todos("   ", [], store=store)
