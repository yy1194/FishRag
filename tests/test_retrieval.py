from __future__ import annotations

from fishrag_rag.retrieval import (
    RetrievalHit,
    build_citations,
    no_evidence_answer,
    rag_search,
    reciprocal_rank_fusion,
)


def test_reciprocal_rank_fusion_merges_duplicate_chunks() -> None:
    vector_hit = RetrievalHit(
        chunk_id="chunk-1",
        document_id="doc-1",
        chunk_index=0,
        content="vector content",
        score=0.8,
        source="vector",
        metadata={"filename": "guide.md"},
    )
    keyword_hit = RetrievalHit(
        chunk_id="chunk-1",
        document_id="doc-1",
        chunk_index=0,
        content="keyword content",
        score=12.0,
        source="keyword",
    )

    fused = reciprocal_rank_fusion([[vector_hit], [keyword_hit]], limit=5)

    assert len(fused) == 1
    assert fused[0].chunk_id == "chunk-1"
    assert fused[0].source == "hybrid"
    assert fused[0].content == "keyword content"
    assert fused[0].metadata["retrieval_sources"] == ["keyword", "vector"]
    assert fused[0].metadata["source_scores"] == {"keyword": 12.0, "vector": 0.8}


def test_rag_search_builds_ordered_citations() -> None:
    hits = [
        RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            chunk_index=0,
            content="first",
            score=0.2,
            source="vector",
        ),
        RetrievalHit(
            chunk_id="chunk-2",
            document_id="doc-1",
            chunk_index=1,
            content="second",
            score=0.1,
            source="keyword",
        ),
    ]

    result = rag_search("question", hits, limit=1)
    citations = build_citations(hits)

    assert len(result.hits) == 1
    assert result.citations[0].id == "C1"
    assert result.citations[0].chunk_id == "chunk-1"
    assert citations[1].id == "C2"


def test_no_evidence_answer_is_explicitly_unanswered() -> None:
    answer = no_evidence_answer("missing question")

    assert not answer.is_answered
    assert answer.citations == []
    assert "没有检索到足够证据" in answer.answer
