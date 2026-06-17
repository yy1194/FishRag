from __future__ import annotations

import pytest

from fishrag_rag.chunking import chunk_text


def test_chunk_text_returns_empty_list_for_blank_text() -> None:
    assert chunk_text("   ") == []


def test_chunk_text_splits_long_text() -> None:
    text = " ".join(f"token-{index}" for index in range(120))

    chunks = chunk_text(text, max_chars=120, overlap_chars=20)

    assert len(chunks) > 1
    assert chunks[0].index == 0
    assert all(chunk.text for chunk in chunks)
    assert all(chunk.char_count <= 120 for chunk in chunks)


def test_chunk_text_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", max_chars=100, overlap_chars=100)
