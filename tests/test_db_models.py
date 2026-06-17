from __future__ import annotations

from fishrag_api.db.base import Base


def test_metadata_contains_stage_one_tables() -> None:
    expected_tables = {
        "users",
        "chat_sessions",
        "messages",
        "documents",
        "document_chunks",
        "agent_tasks",
        "approvals",
        "memories",
    }

    assert expected_tables.issubset(set(Base.metadata.tables))
