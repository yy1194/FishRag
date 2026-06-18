from __future__ import annotations

from fishrag_api.db.base import Base
from fishrag_api.db.types import VectorType


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
        "rag_evaluation_jobs",
    }

    assert expected_tables.issubset(set(Base.metadata.tables))


def test_vector_type_serializes_and_reads_pgvector_text() -> None:
    vector_type = VectorType(3)
    bind = vector_type.bind_processor(None)
    result = vector_type.result_processor(None, None)

    assert bind([1, 2.5, 3]) == "[1.0,2.5,3.0]"
    assert result("[1,2.5,3]") == [1.0, 2.5, 3.0]
