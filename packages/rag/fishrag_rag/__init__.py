"""RAG ingestion, retrieval, and evaluation primitives."""

from fishrag_rag.chunking import chunk_text
from fishrag_rag.schemas import DocumentChunk

__all__ = ["DocumentChunk", "chunk_text"]
