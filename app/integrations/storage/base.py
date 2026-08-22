from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageProvider(Protocol):
    """Raw document storage — implemented by S3 today, swappable to any object store."""

    def upload(self, key: str, data: bytes) -> None: ...

    def download(self, key: str) -> bytes: ...

    def list(self, prefix: str = "") -> list[str]: ...

    def delete(self, key: str) -> None: ...
