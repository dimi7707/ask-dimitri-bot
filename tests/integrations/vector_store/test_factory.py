import pytest

from app.core.config import Settings
from app.integrations.vector_store import factory as vector_store_factory
from app.integrations.vector_store.base import EmbeddedChunk, RetrievedChunk, VectorStoreProvider


class FakeVectorStoreProvider:
    def __init__(self):
        self._documents: dict[str, dict] = {}
        self._chunks_by_document: dict[str, list[EmbeddedChunk]] = {}

    def upsert_document(self, document_id: str, filename: str, doc_type: str, version: str) -> None:
        self._documents[document_id] = {"filename": filename, "doc_type": doc_type, "version": version}

    def upsert_chunks(self, document_id: str, chunks: list[EmbeddedChunk]) -> None:
        self._chunks_by_document[document_id] = chunks

    def delete_by_document_id(self, document_id: str) -> None:
        self._chunks_by_document.pop(document_id, None)

    def similarity_search(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        results = [
            RetrievedChunk(chunk_text=chunk.chunk_text, score=1.0, document_id=document_id)
            for document_id, chunks in self._chunks_by_document.items()
            for chunk in chunks
        ]
        return results[:top_k]


def test_fake_vector_store_provider_satisfies_the_protocol():
    assert isinstance(FakeVectorStoreProvider(), VectorStoreProvider)


def test_get_vector_store_provider_dispatches_to_the_configured_provider(monkeypatch):
    monkeypatch.setitem(vector_store_factory.PROVIDERS, "fake", FakeVectorStoreProvider)
    settings = Settings(_env_file=None, vector_store_provider="fake")

    provider = vector_store_factory.get_vector_store_provider(settings=settings)

    assert isinstance(provider, FakeVectorStoreProvider)


def test_get_vector_store_provider_defaults_to_pgvector():
    from app.integrations.vector_store.pgvector_provider import PgVectorStoreProvider

    provider = vector_store_factory.get_vector_store_provider(settings=Settings(_env_file=None))

    assert isinstance(provider, PgVectorStoreProvider)


def test_get_vector_store_provider_raises_on_unregistered_provider():
    settings = Settings(_env_file=None, vector_store_provider="does-not-exist")

    with pytest.raises(ValueError, match="does-not-exist"):
        vector_store_factory.get_vector_store_provider(settings=settings)


def test_fake_vector_store_upsert_delete_and_similarity_search():
    provider = FakeVectorStoreProvider()
    chunk = EmbeddedChunk(chunk_text="Dimitri uses Python", embedding=[0.1, 0.2], chunk_index=0)

    provider.upsert_document("doc-1", filename="cv.pdf", doc_type="cv", version="v1")
    provider.upsert_chunks("doc-1", [chunk])
    results = provider.similarity_search(query_embedding=[0.1, 0.2], top_k=5)

    assert len(results) == 1
    assert results[0].chunk_text == "Dimitri uses Python"
    assert results[0].document_id == "doc-1"

    provider.delete_by_document_id("doc-1")

    assert provider.similarity_search(query_embedding=[0.1, 0.2], top_k=5) == []
