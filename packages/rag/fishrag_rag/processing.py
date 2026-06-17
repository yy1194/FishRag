from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from fishrag_rag.chunking import chunk_text
from fishrag_rag.parsing import ParsedDocument
from fishrag_rag.schemas import DocumentChunk


class DocumentProcessingError(Exception):
    """Raised when parsed text cannot be converted into chunks."""


@dataclass(frozen=True)
class CleanedDocumentText:
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TextSection:
    index: int
    title: str
    level: int
    start: int
    end: int
    path: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChunkedDocument:
    chunks: list[DocumentChunk]
    sections: list[TextSection]
    cleaned_text: str
    metadata: dict[str, Any]


def clean_document_text(text: str) -> CleanedDocumentText:
    original_length = len(text)
    normalized = text.replace("\ufeff", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(?<=\w)-\n(?=\w)", "", normalized)
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()

    if not normalized:
        raise DocumentProcessingError("Cleaned document has no readable text.")

    return CleanedDocumentText(
        text=normalized,
        metadata={
            "original_length": original_length,
            "cleaned_length": len(normalized),
            "line_count": len(normalized.splitlines()),
        },
    )


def detect_text_sections(text: str) -> list[TextSection]:
    candidates = _section_candidates(text)
    if not candidates:
        return []

    sections: list[TextSection] = []
    stack: list[TextSection] = []
    for index, candidate in enumerate(candidates):
        next_start = (
            int(candidates[index + 1]["start"])
            if index + 1 < len(candidates)
            else len(text)
        )
        level = int(candidate["level"])
        title = str(candidate["title"])

        stack = [section for section in stack if section.level < level]
        path = tuple([section.title for section in stack] + [title])
        section = TextSection(
            index=index,
            title=title,
            level=level,
            start=int(candidate["start"]),
            end=next_start,
            path=path,
        )
        sections.append(section)
        stack.append(section)

    return sections


def build_chunked_document(
    parsed: ParsedDocument,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> ChunkedDocument:
    cleaned = clean_document_text(parsed.text)
    sections = detect_text_sections(cleaned.text)
    chunks = chunk_text(
        cleaned.text,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        metadata={"source_type": parsed.source_type, "parser": parsed.parser},
    )
    if not chunks:
        raise DocumentProcessingError("Document did not produce any chunks.")

    enriched_chunks = [
        _with_chunk_metadata(chunk, section=_section_for_offset(sections, chunk.start))
        for chunk in chunks
    ]
    return ChunkedDocument(
        chunks=enriched_chunks,
        sections=sections,
        cleaned_text=cleaned.text,
        metadata={
            "cleaning": cleaned.metadata,
            "chunk_count": len(enriched_chunks),
            "section_count": len(sections),
            "max_chars": max_chars,
            "overlap_chars": overlap_chars,
        },
    )


def estimate_token_count(text: str) -> int:
    if not text.strip():
        return 0
    cjk_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    non_cjk_chars = max(len(text) - cjk_chars, 0)
    return max(1, math.ceil(cjk_chars / 1.6 + non_cjk_chars / 4))


def _section_candidates(text: str) -> list[dict[str, int | str]]:
    candidates: list[dict[str, int | str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        markdown = re.match(r"^(#{1,6})\s+(.{1,120})$", stripped)
        numbered = re.match(
            r"^((?:\d+(?:\.\d+)*|第[一二三四五六七八九十百千万0-9]+[章节篇部分]))"
            r"[、.\s]+(.{2,120})$",
            stripped,
        )
        if markdown:
            candidates.append(
                {
                    "level": len(markdown.group(1)),
                    "title": markdown.group(2).strip(),
                    "start": offset,
                }
            )
        elif numbered:
            marker = numbered.group(1)
            title = numbered.group(2).strip()
            candidates.append(
                {
                    "level": _numbered_heading_level(marker),
                    "title": title,
                    "start": offset,
                }
            )
        offset += len(line)
    return candidates


def _numbered_heading_level(marker: str) -> int:
    if marker.startswith("第"):
        if marker.endswith(("章", "篇", "部分")):
            return 1
        return 2
    return marker.count(".") + 1


def _section_for_offset(sections: list[TextSection], offset: int) -> TextSection | None:
    for section in reversed(sections):
        if section.start <= offset < section.end:
            return section
    return None


def _with_chunk_metadata(
    chunk: DocumentChunk,
    *,
    section: TextSection | None,
) -> DocumentChunk:
    metadata = dict(chunk.metadata)
    metadata.update(
        {
            "start": chunk.start,
            "end": chunk.end,
            "char_count": chunk.char_count,
            "token_count": estimate_token_count(chunk.text),
        }
    )
    if section is not None:
        metadata.update(
            {
                "section_index": section.index,
                "section_title": section.title,
                "section_level": section.level,
                "section_path": list(section.path),
            }
        )
    return DocumentChunk(
        index=chunk.index,
        text=chunk.text,
        start=chunk.start,
        end=chunk.end,
        metadata=metadata,
    )
