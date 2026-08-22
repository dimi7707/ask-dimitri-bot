import pytest

from app.core.config import Settings
from app.integrations.document_processing import factory as document_processing_factory
from app.integrations.document_processing.base import DocumentChunk, DocumentProcessor


class FakeDocumentProcessor:
    def load_and_chunk(self, path: str) -> list[DocumentChunk]:
        return [DocumentChunk(chunk_text=f"chunk from {path}", chunk_index=0)]


def test_fake_document_processor_satisfies_the_protocol():
    assert isinstance(FakeDocumentProcessor(), DocumentProcessor)


def test_get_document_processor_dispatches_to_the_configured_provider(monkeypatch):
    monkeypatch.setitem(document_processing_factory.PROVIDERS, "fake", FakeDocumentProcessor)
    settings = Settings(_env_file=None, document_processor="fake")

    processor = document_processing_factory.get_document_processor(settings=settings)

    assert isinstance(processor, FakeDocumentProcessor)


def test_get_document_processor_raises_on_unregistered_provider():
    settings = Settings(_env_file=None, document_processor="does-not-exist")

    with pytest.raises(ValueError, match="does-not-exist"):
        document_processing_factory.get_document_processor(settings=settings)


def test_fake_document_processor_loads_and_chunks_a_file():
    processor = FakeDocumentProcessor()

    chunks = processor.load_and_chunk("cv.pdf")

    assert chunks == [DocumentChunk(chunk_text="chunk from cv.pdf", chunk_index=0)]
