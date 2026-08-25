from pathlib import Path

import pytest

from app.integrations.document_processing.base import DocumentChunk, UnsupportedDocumentTypeError
from ingestion.ingest import document_id_for, ingest_all, ingest_document

CV_BYTES = b"Dimitri Avila\nDesarrollador backend\nPython, FastAPI y AWS"


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self._objects = dict(objects)

    def upload(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    def download(self, key: str) -> bytes:
        return self._objects[key]

    def list(self, prefix: str = "") -> list[str]:
        return sorted(key for key in self._objects if key.startswith(prefix))

    def delete(self, key: str) -> None:
        del self._objects[key]


class FakeDocumentProcessor:
    """Chunks the file line by line, so tests can assert the downloaded bytes reached disk."""

    SUPPORTED = {".pdf", ".docx", ".pptx"}

    def load_and_chunk(self, path: str) -> list[DocumentChunk]:
        source = Path(path)
        if source.suffix.lower() not in self.SUPPORTED:
            raise UnsupportedDocumentTypeError(f"unsupported extension {source.suffix!r}")
        return [
            DocumentChunk(chunk_text=line, chunk_index=index, metadata={"file_name": source.name})
            for index, line in enumerate(source.read_bytes().decode().splitlines())
        ]


class FakeEmbeddingProvider:
    def __init__(self):
        self.embedded_texts: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        return [float(len(text)), 0.0, 1.0]


class FakeVectorStore:
    """Append-only on purpose: replacing prior chunks must be driven by ingestion, not by the fake."""

    def __init__(self):
        self.documents: dict[str, dict] = {}
        self.chunks: list[tuple[str, object]] = []

    def upsert_document(self, document_id: str, filename: str, doc_type: str, version: str) -> None:
        self.documents[document_id] = {"filename": filename, "doc_type": doc_type, "version": version}

    def upsert_chunks(self, document_id: str, chunks: list) -> None:
        self.chunks.extend((document_id, chunk) for chunk in chunks)

    def delete_by_document_id(self, document_id: str) -> None:
        self.chunks = [row for row in self.chunks if row[0] != document_id]

    def similarity_search(self, query_embedding: list[float], top_k: int) -> list:
        return []

    def chunks_for(self, document_id: str) -> list:
        return [chunk for owner_id, chunk in self.chunks if owner_id == document_id]


@pytest.fixture
def providers():
    return {
        "storage": FakeStorage({"documents/cv.pdf": CV_BYTES}),
        "processor": FakeDocumentProcessor(),
        "embedder": FakeEmbeddingProvider(),
        "vector_store": FakeVectorStore(),
    }


def test_ingest_document_records_the_document_metadata():
    vector_store = FakeVectorStore()

    result = ingest_document(
        "documents/cv.pdf",
        storage=FakeStorage({"documents/cv.pdf": CV_BYTES}),
        processor=FakeDocumentProcessor(),
        embedder=FakeEmbeddingProvider(),
        vector_store=vector_store,
        version="2026-08-25",
    )

    assert vector_store.documents[result.document_id] == {
        "filename": "cv.pdf",
        "doc_type": "pdf",
        "version": "2026-08-25",
    }


def test_ingest_document_persists_one_chunk_per_chunk_produced(providers):
    result = ingest_document("documents/cv.pdf", **providers)

    stored = providers["vector_store"].chunks_for(result.document_id)
    assert [chunk.chunk_text for chunk in stored] == [
        "Dimitri Avila",
        "Desarrollador backend",
        "Python, FastAPI y AWS",
    ]
    assert [chunk.chunk_index for chunk in stored] == [0, 1, 2]
    assert result.chunks_ingested == 3


def test_ingest_document_embeds_every_chunk_and_stores_the_vector(providers):
    result = ingest_document("documents/cv.pdf", **providers)

    assert providers["embedder"].embedded_texts == [
        "Dimitri Avila",
        "Desarrollador backend",
        "Python, FastAPI y AWS",
    ]
    stored = providers["vector_store"].chunks_for(result.document_id)
    assert stored[0].embedding == [float(len("Dimitri Avila")), 0.0, 1.0]


def test_ingest_document_carries_the_processor_metadata_into_the_stored_chunks(providers):
    result = ingest_document("documents/cv.pdf", **providers)

    stored = providers["vector_store"].chunks_for(result.document_id)
    assert all(chunk.metadata["file_name"] == "cv.pdf" for chunk in stored)


def test_ingest_document_rejects_an_unsupported_file_type_without_persisting_anything():
    vector_store = FakeVectorStore()

    with pytest.raises(UnsupportedDocumentTypeError, match=".txt"):
        ingest_document(
            "documents/notes.txt",
            storage=FakeStorage({"documents/notes.txt": b"plain text"}),
            processor=FakeDocumentProcessor(),
            embedder=FakeEmbeddingProvider(),
            vector_store=vector_store,
        )

    assert vector_store.documents == {}
    assert vector_store.chunks == []


def test_reingesting_a_document_replaces_its_previous_chunks(providers):
    ingest_document("documents/cv.pdf", **providers)
    providers["storage"].upload("documents/cv.pdf", b"Dimitri Avila\nAhora tambien con Terraform")

    result = ingest_document("documents/cv.pdf", **providers)

    stored = providers["vector_store"].chunks_for(result.document_id)
    assert [chunk.chunk_text for chunk in stored] == [
        "Dimitri Avila",
        "Ahora tambien con Terraform",
    ]


def test_ingesting_one_document_leaves_other_documents_chunks_untouched(providers):
    providers["storage"].upload("documents/profile.pptx", b"Perfil profesional")
    profile = ingest_document("documents/profile.pptx", **providers)
    cv = ingest_document("documents/cv.pdf", **providers)

    ingest_document("documents/cv.pdf", **providers)

    assert [chunk.chunk_text for chunk in providers["vector_store"].chunks_for(profile.document_id)] == [
        "Perfil profesional"
    ]
    assert len(providers["vector_store"].chunks_for(cv.document_id)) == 3


def test_document_id_is_derived_deterministically_from_the_storage_key():
    assert document_id_for("documents/cv.pdf") == document_id_for("documents/cv.pdf")
    assert document_id_for("documents/cv.pdf") != document_id_for("documents/profile.pdf")


def test_ingest_all_ingests_every_object_under_the_prefix(providers):
    providers["storage"].upload("documents/profile.pptx", b"Perfil profesional")

    results = ingest_all(prefix="documents/", **providers)

    assert sorted(result.key for result in results) == ["documents/cv.pdf", "documents/profile.pptx"]
    assert len(providers["vector_store"].documents) == 2


def test_ingest_all_skips_unsupported_files_and_still_ingests_the_supported_ones(providers):
    providers["storage"].upload("documents/readme.txt", b"not a document")

    results = ingest_all(prefix="documents/", **providers)

    assert [result.key for result in results] == ["documents/cv.pdf"]
    assert len(providers["vector_store"].documents) == 1
