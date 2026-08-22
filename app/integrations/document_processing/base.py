from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class DocumentChunk:
    chunk_text: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class DocumentProcessor(Protocol):
    """File -> chunks — implemented by LlamaIndex today, swappable to any parsing library."""

    def load_and_chunk(self, path: str) -> list[DocumentChunk]: ...
