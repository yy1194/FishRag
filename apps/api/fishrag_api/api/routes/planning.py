from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fishrag_agent.planning import InMemoryTodoStore, TodoDraft, TodoSnapshot, write_todos
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/planning", tags=["planning"])
todo_store = InMemoryTodoStore()

TodoStatus = Literal["pending", "in_progress", "completed", "blocked", "cancelled"]


class TodoWriteItem(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=2000)
    status: TodoStatus = "pending"

    model_config = ConfigDict(extra="forbid")


class WriteTodosRequest(BaseModel):
    todos: list[TodoWriteItem] = Field(default_factory=list, max_length=200)

    model_config = ConfigDict(extra="forbid")


class TodoResponse(BaseModel):
    id: str
    content: str
    status: TodoStatus
    created_at: str
    updated_at: str


class TodoStatsResponse(BaseModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    blocked: int
    cancelled: int


class TodoListResponse(BaseModel):
    session_id: str
    todos: list[TodoResponse]
    stats: TodoStatsResponse
    updated_at: str


def _to_response(snapshot: TodoSnapshot) -> TodoListResponse:
    data = snapshot.as_dict()
    return TodoListResponse.model_validate(data)


@router.get("/sessions/{session_id}/todos", response_model=TodoListResponse)
async def get_todos(session_id: str) -> TodoListResponse:
    try:
        return _to_response(todo_store.get(session_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/sessions/{session_id}/todos", response_model=TodoListResponse)
async def put_todos(session_id: str, request: WriteTodosRequest) -> TodoListResponse:
    try:
        drafts = [
            TodoDraft(id=item.id, content=item.content, status=item.status)
            for item in request.todos
        ]
        return _to_response(write_todos(session_id, drafts, store=todo_store))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}/todos", response_model=TodoListResponse)
async def delete_todos(session_id: str) -> TodoListResponse:
    try:
        return _to_response(todo_store.clear(session_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
