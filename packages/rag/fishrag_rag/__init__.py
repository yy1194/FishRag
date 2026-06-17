"""RAG ingestion, retrieval, and evaluation primitives."""

from fishrag_rag.chunking import chunk_text
from fishrag_rag.documents import (
    DocumentStatus,
    build_document_storage_path,
    can_transition_document_status,
    sanitize_document_filename,
    validate_document_status_transition,
)
from fishrag_rag.embeddings import (
    EmbeddingBatch,
    EmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingProviderError,
    EmbeddingResponseError,
    OpenAICompatibleEmbeddingClient,
)
from fishrag_rag.keyword_index import (
    KeywordIndexBatchResult,
    KeywordIndexClient,
    KeywordIndexConfigurationError,
    KeywordIndexDocument,
    KeywordIndexError,
    KeywordIndexProviderError,
    KeywordIndexResponseError,
    OpenSearchKeywordIndexClient,
)
from fishrag_rag.parsing import (
    DocumentParseError,
    ParsedDocument,
    UnsupportedDocumentFormatError,
    infer_document_type,
    parse_document_file,
)
from fishrag_rag.processing import (
    ChunkedDocument,
    CleanedDocumentText,
    DocumentProcessingError,
    TextSection,
    build_chunked_document,
    clean_document_text,
    detect_text_sections,
    estimate_token_count,
)
from fishrag_rag.schemas import DocumentChunk

__all__ = [
    "DocumentChunk",
    "DocumentParseError",
    "DocumentProcessingError",
    "DocumentStatus",
    "EmbeddingBatch",
    "EmbeddingClient",
    "EmbeddingConfigurationError",
    "EmbeddingError",
    "EmbeddingProviderError",
    "EmbeddingResponseError",
    "KeywordIndexBatchResult",
    "KeywordIndexClient",
    "KeywordIndexConfigurationError",
    "KeywordIndexDocument",
    "KeywordIndexError",
    "KeywordIndexProviderError",
    "KeywordIndexResponseError",
    "OpenAICompatibleEmbeddingClient",
    "OpenSearchKeywordIndexClient",
    "ParsedDocument",
    "ChunkedDocument",
    "CleanedDocumentText",
    "TextSection",
    "UnsupportedDocumentFormatError",
    "build_chunked_document",
    "build_document_storage_path",
    "can_transition_document_status",
    "chunk_text",
    "clean_document_text",
    "detect_text_sections",
    "estimate_token_count",
    "infer_document_type",
    "parse_document_file",
    "sanitize_document_filename",
    "validate_document_status_transition",
]
