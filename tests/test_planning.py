from __future__ import annotations

import pytest

from fishrag_agent.planning import TodoItem, TodoList, validate_todos


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
