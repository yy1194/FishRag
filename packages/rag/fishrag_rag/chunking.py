from __future__ import annotations

from fishrag_rag.schemas import DocumentChunk


def chunk_text(
    text: str,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
    metadata: dict[str, str] | None = None,
) -> list[DocumentChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero.")
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative.")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars.")

    normalized = text.strip()
    if not normalized:
        return []

    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    base_metadata = metadata or {}

    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            boundary = _best_boundary(normalized, start, end)
            if boundary > start:
                end = boundary

        chunk_body = normalized[start:end].strip()
        if chunk_body:
            chunks.append(
                DocumentChunk(
                    index=index,
                    text=chunk_body,
                    start=start,
                    end=end,
                    metadata=base_metadata,
                )
            )
            index += 1

        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)

    return chunks


def _best_boundary(text: str, start: int, end: int) -> int:
    min_boundary = start + ((end - start) // 2)
    candidates = [
        text.rfind("\n\n", start, end),
        text.rfind("。", start, end),
        text.rfind(".", start, end),
        text.rfind("\n", start, end),
        text.rfind(" ", start, end),
    ]
    usable = [candidate + 1 for candidate in candidates if candidate >= min_boundary]
    return max(usable, default=end)
