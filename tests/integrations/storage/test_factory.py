import pytest

from app.core.config import Settings
from app.integrations.storage import factory as storage_factory
from app.integrations.storage.base import StorageProvider


class FakeStorageProvider:
    def __init__(self):
        self._objects: dict[str, bytes] = {}

    def upload(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    def download(self, key: str) -> bytes:
        return self._objects[key]

    def list(self, prefix: str = "") -> list[str]:
        return [key for key in self._objects if key.startswith(prefix)]

    def delete(self, key: str) -> None:
        del self._objects[key]


def test_fake_storage_provider_satisfies_the_protocol():
    assert isinstance(FakeStorageProvider(), StorageProvider)


def test_get_storage_provider_dispatches_to_the_configured_provider(monkeypatch):
    monkeypatch.setitem(storage_factory.PROVIDERS, "fake", FakeStorageProvider)
    settings = Settings(_env_file=None, storage_provider="fake")

    provider = storage_factory.get_storage_provider(settings=settings)

    assert isinstance(provider, FakeStorageProvider)


def test_get_storage_provider_raises_on_unregistered_provider():
    settings = Settings(_env_file=None, storage_provider="does-not-exist")

    with pytest.raises(ValueError, match="does-not-exist"):
        storage_factory.get_storage_provider(settings=settings)


def test_fake_storage_provider_round_trips_upload_download_list_delete():
    provider = FakeStorageProvider()

    provider.upload("docs/cv.pdf", b"cv-bytes")
    provider.upload("docs/profile.pdf", b"profile-bytes")

    assert provider.download("docs/cv.pdf") == b"cv-bytes"
    assert sorted(provider.list(prefix="docs/")) == ["docs/cv.pdf", "docs/profile.pdf"]

    provider.delete("docs/cv.pdf")

    assert provider.list(prefix="docs/") == ["docs/profile.pdf"]
