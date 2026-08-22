from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Text -> vector — implemented by Bedrock Titan today, swappable to any embedding model."""

    def embed(self, text: str) -> list[float]: ...
