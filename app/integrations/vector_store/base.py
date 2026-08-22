from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class EmbeddedChunk:
    chunk_text: str
    embedding: list[float]
    chunk_index: int
    metadata: dict = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    chunk_text: str
    score: float
    document_id: str


@runtime_checkable
class VectorStoreProvider(Protocol):
    """Document/chunk persistence + similarity search — implemented by pgvector today."""

    def upsert_document(self, document_id: str, filename: str, doc_type: str, version: str) -> None: ...

    def upsert_chunks(self, document_id: str, chunks: list[EmbeddedChunk]) -> None: ...

    def delete_by_document_id(self, document_id: str) -> None: ...

    def similarity_search(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]: ...
